"""MCP server. Thin layer: runs each task in the sandbox and adapts errors.

Transport from STEP_BY_STEP_MATH_TRANSPORT: stdio (default) or http.

The whiteboard is an MCP App: `integrate` points at the `ui://` board resource,
the host renders it, and the page loads the steps through `get_board`, a tool
only the app can call. The model gets a compact summary, never the steps.
Hosts without MCP Apps get a link to the same board instead.
"""

import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

import uvicorn
from mcp.server.apps import Apps, ResourceCsp
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from step_by_step_math import tasks
from step_by_step_math.board import KATEX_ORIGIN, PAGE_CSP, app_html, page_html
from step_by_step_math.boards import BoardStore
from step_by_step_math.errors import UserFacingError
from step_by_step_math.sandbox import (
    default_memory_mb,
    default_timeout,
    max_concurrent,
    run_isolated,
    warm_up,
)

BOARD_URI = "ui://step-by-step-math/board-v1.html"  # bump the version on breaking changes (hosts cache it)

_PURE = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)

_SYNTAX = (
    "Expression syntax (SymPy): x**2 (or x^2), 3*x (explicit multiplication), "
    "sin(x), cos(x), tan(x), exp(x), log(x) (natural log), sqrt(x), asin(x), atan(x). "
    "Also accepts sen, tg and ln. Constants: pi, E, oo (infinity)."
)

boards = BoardStore()

# Where links to boards point. Set in main(): a public URL over http, a folder over stdio.
_board_base_url: str | None = None
_board_dir: Path | None = None


def _run(task: Callable[..., Any], *args: Any) -> Any:
    try:
        return run_isolated(task, *args)
    except UserFacingError as e:
        raise ToolError(str(e)) from None


def _publish_board(board: dict[str, Any]) -> dict[str, str]:
    board_id = boards.put(board)
    links = {"board_id": board_id}
    if _board_base_url:
        links["board_url"] = f"{_board_base_url}/board/{board_id}"
    elif _board_dir is not None:
        path = _board_dir / f"{board_id}.html"
        path.write_text(page_html({**board, "id": board_id}), encoding="utf-8")
        links["board_path"] = str(path)
    return links


class DerivativeResult(TypedDict):
    result: str  # SymPy syntax, reusable as input
    latex: str
    variable: str


class IntegralResult(TypedDict):
    kind: Literal["indefinite", "definite"]
    result: str | None  # includes "+ C" when indefinite; None when it diverges
    latex: str | None
    method: Literal["auto", "parts", "substitution", "partial_fractions"]
    verification: Literal["verified", "inconclusive"]
    steps: int
    board_id: str
    board_url: NotRequired[str]
    board_path: NotRequired[str]
    generic_fallback: NotRequired[bool]
    status: NotRequired[Literal["converges", "diverges"]]
    improper: NotRequired[bool]
    discontinuities: NotRequired[list[str]]
    explanation: NotRequired[str]
    warnings: NotRequired[list[str]]


class VerificationResult(TypedDict):
    status: Literal["verified", "inconclusive", "incorrect"]
    difference: NotRequired[str]
    difference_latex: NotRequired[str]
    note: NotRequired[str]


# --- Tools bound to the whiteboard (MCP Apps) ----------------------------------------

apps = Apps()
apps.add_html_resource(
    BOARD_URI,
    app_html(),
    name="Pizarrón",
    description="Step-by-step whiteboard",
    csp=ResourceCsp(resource_domains=[KATEX_ORIGIN]),
    prefers_border=False,
)


@apps.tool(
    resource_uri=BOARD_URI,
    description=(
        "Integrate an expression step by step with a symbolic engine (SymPy) and show every step "
        "on a visual whiteboard. NEVER integrate by hand and never change the result. "
        "method: 'auto' (default) or the method the user asks for: 'parts' (give u, optionally dv), "
        "'substitution' (give u as a function of the variable, e.g. 'x**2'), 'partial_fractions'. "
        "Use exactly the method and u the user chose; if the tool returns an error, tell the user and "
        "do not switch methods on your own. "
        "The user already sees all the steps on the whiteboard: do NOT rewrite or recompute them in "
        "your reply. Answer with the result and at most one short sentence about the method. "
        "If the whiteboard is not displayed in this app, give the user board_url (or board_path). "
        "Indefinite: omit 'lower'/'upper'; the result includes + C. Definite: give both limits "
        "(0, pi/2, E, oo, -oo); discontinuities are handled as improper integrals and status may be "
        "'diverges' with an explanation. 'verification' is 'verified' or 'inconclusive' (only numeric). "
        "If the user brings their own antiderivative, use verify_antiderivative instead. "
        f"{_SYNTAX}"
    ),
    annotations=_PURE,
)
def integrate(
    expression: str,
    variable: str = "x",
    lower: str | int | float | None = None,
    upper: str | int | float | None = None,
    method: Literal["auto", "parts", "substitution", "partial_fractions"] = "auto",
    u: str | None = None,
    dv: str | None = None,
) -> IntegralResult:
    # Clients and models often send limits as JSON numbers (0, -1, 2.5).
    lower, upper = (None if v is None else str(v) for v in (lower, upper))
    out = _run(tasks.integrate_task, expression, variable, lower, upper, method, u, dv)
    board = out.pop("board")
    return {**out, **_publish_board(board)}  # type: ignore[typeddict-item]


server = MCPServer(
    name="step-by-step-math",
    instructions=(
        "Symbolic math engine (SymPy). Never compute by hand: "
        "use these tools for every calculation and show their result as is."
    ),
    extensions=[apps],
)


@server.tool(
    description="Internal: loads a whiteboard's steps for the whiteboard UI. Do not call it.",
    annotations=_PURE,
    meta={"ui": {"visibility": ["app"]}},
)
def get_board(board_id: str) -> dict[str, Any]:
    # Only reads the in-memory store: no sandbox, no computation slot.
    board = boards.get(board_id)
    if board is None:
        raise ToolError("This whiteboard expired (boards last 1 hour). Solve the integral again.")
    return board


# --- Plain tools -----------------------------------------------------------------------

@server.tool(
    description=(
        "Differentiate an expression with respect to a variable using a symbolic engine (SymPy). "
        "ALWAYS use it when a derivative is needed: do not differentiate by hand or adjust the result. "
        f"{_SYNTAX} Returns the result in SymPy syntax and in LaTeX."
    ),
    annotations=_PURE,
)
def differentiate(expression: str, variable: str = "x") -> DerivativeResult:
    return _run(tasks.differentiate_task, expression, variable)


@server.tool(
    description=(
        "Check whether 'antiderivative' is a correct antiderivative of 'integrand' by differentiating it "
        "with a symbolic engine (SymPy). Use it whenever the user brings their own integration result: "
        "never compare or check by hand. Results that differ by a constant are correct. "
        "status: 'verified' (proven), 'inconclusive' (numerically correct but not proven symbolically) "
        "or 'incorrect' (with the simplified difference d/dx(antiderivative) - integrand). "
        f"{_SYNTAX} A '+ C' in the antiderivative is fine."
    ),
    annotations=_PURE,
)
def verify_antiderivative(integrand: str, antiderivative: str, variable: str = "x") -> VerificationResult:
    return _run(tasks.verify_task, integrand, antiderivative, variable)


# --- HTTP routes ---------------------------------------------------------------------------
# claude.ai (static headers are a limited beta) and ChatGPT (OAuth or none) do not
# let a custom connector send a fixed token, so the MCP endpoint lives at a secret
# path: /mcp/<token>. The full URL is the secret. No OAuth for now.
# Boards are served at /board/<id> WITHOUT the server token: sharing a board link
# must not leak access to the server. Board ids are random and expire.

_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,}$")
_TOKEN_HELP = 'Generate one with: python3 -c "import secrets; print(secrets.token_urlsafe(32))"'
_PAGE_HEADERS = {
    "Content-Security-Policy": PAGE_CSP,
    "Referrer-Policy": "no-referrer",  # the board id must not leak to cdnjs
    "X-Robots-Tag": "noindex",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


@server.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok"})


@server.custom_route("/board/{board_id}", methods=["GET"], include_in_schema=False)
async def board_page(request: Request) -> Response:
    board = boards.get(request.path_params["board_id"])
    if board is None:
        return HTMLResponse("<!doctype html><meta charset=utf-8><title>Pizarrón</title>"
                            "<p>Este pizarrón no existe o ya venció (duran 1 hora).</p>",
                            status_code=404, headers=_PAGE_HEADERS)
    return HTMLResponse(page_html(board), headers=_PAGE_HEADERS)


def path_token() -> str:
    token = os.environ.get("STEP_BY_STEP_MATH_PATH_TOKEN", "").strip()
    if not _TOKEN_PATTERN.match(token):
        raise SystemExit(
            "STEP_BY_STEP_MATH_PATH_TOKEN must be set to at least 32 URL-safe characters "
            f"(A-Z, a-z, 0-9, -, _) when the transport is http. {_TOKEN_HELP}"
        )
    return token


def public_base_url() -> str | None:
    """Public URL of the server, for board links: explicit, or Railway's domain."""
    explicit = os.environ.get("STEP_BY_STEP_MATH_PUBLIC_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    railway = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    return f"https://{railway}" if railway else None


def http_app(token: str) -> Starlette:
    # Stateless + JSON responses: no session survives a redeploy anyway, and each
    # tool call is a single request/response.
    return server.streamable_http_app(
        streamable_http_path=f"/mcp/{token}",
        stateless_http=True,
        json_response=True,
        host="0.0.0.0",
    )


def run_http() -> None:
    global _board_base_url
    token = path_token()
    _board_base_url = public_base_url()
    if _board_base_url is None:
        print("warning: no STEP_BY_STEP_MATH_PUBLIC_URL or RAILWAY_PUBLIC_DOMAIN; "
              "integrate will not return board links", flush=True)
    port = int(os.environ.get("PORT", "8000"))
    # access_log=False: request paths contain the token or board ids and must not reach the logs.
    uvicorn.run(http_app(token), host="0.0.0.0", port=port, access_log=False, log_level="info")


def run_stdio() -> None:
    global _board_dir
    # No HTTP server here: boards are written as local HTML files (useful in Claude Code).
    _board_dir = Path(tempfile.gettempdir()) / "step-by-step-math-boards"
    _board_dir.mkdir(mode=0o700, exist_ok=True)
    server.run("stdio")


def main() -> None:
    # Fail fast on bad configuration.
    default_timeout()
    default_memory_mb()
    max_concurrent()
    transport = os.environ.get("STEP_BY_STEP_MATH_TRANSPORT", "stdio").strip().lower()
    if transport not in ("stdio", "http"):
        raise SystemExit(f"STEP_BY_STEP_MATH_TRANSPORT must be 'stdio' or 'http', got {transport!r}")

    warm_up()
    if transport == "stdio":
        run_stdio()
    else:
        run_http()


if __name__ == "__main__":
    main()
