"""MCP server. Thin layer: runs each task in the sandbox and adapts errors.

Transport from STEP_BY_STEP_MATH_TRANSPORT: stdio (default) or http.
"""

import os
import re
from collections.abc import Callable
from typing import Any, Literal, NotRequired, TypedDict

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from step_by_step_math import tasks
from step_by_step_math.errors import UserFacingError
from step_by_step_math.sandbox import (
    default_memory_mb,
    default_timeout,
    max_concurrent,
    run_isolated,
    warm_up,
)

server = MCPServer(
    name="step-by-step-math",
    instructions=(
        "Symbolic math engine (SymPy). Never compute by hand: "
        "use these tools for every calculation and show their result as is."
    ),
)

_PURE = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)

_SYNTAX = (
    "Expression syntax (SymPy): x**2 (or x^2), 3*x (explicit multiplication), "
    "sin(x), cos(x), tan(x), exp(x), log(x) (natural log), sqrt(x), asin(x), atan(x). "
    "Also accepts sen, tg and ln. Constants: pi, E, oo (infinity)."
)


def _run(task: Callable[..., Any], *args: Any) -> Any:
    try:
        return run_isolated(task, *args)
    except UserFacingError as e:
        raise ToolError(str(e)) from None


class DerivativeResult(TypedDict):
    result: str  # SymPy syntax, reusable as input
    latex: str
    variable: str


class IntegralResult(TypedDict):
    kind: Literal["indefinite", "definite"]
    result: str | None  # includes "+ C" when indefinite; None when it diverges
    latex: str | None
    method: Literal["manualintegrate", "integrate_fallback"]
    verification: Literal["verified", "inconclusive"]
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
        "Integrate an expression with a symbolic engine (SymPy), indefinite or definite. "
        "NEVER integrate by hand and never change the result: show it as returned. "
        "Indefinite: omit 'lower' and 'upper'; the result includes + C. "
        "Definite: give both limits (constants like 0, pi/2, E, oo, -oo). Discontinuities in the "
        "interval are detected and handled as improper integrals; if it diverges, "
        "status is 'diverges' with an explanation. "
        "'method' says whether a textbook-style method (manualintegrate) or the generic fallback was used. "
        "'verification' is 'verified' (checked by differentiating) or 'inconclusive' (only numerically). "
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
) -> IntegralResult:
    # Clients and models often send limits as JSON numbers (0, -1, 2.5).
    lower, upper = (None if v is None else str(v) for v in (lower, upper))
    return _run(tasks.integrate_task, expression, variable, lower, upper)


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


# --- HTTP transport -------------------------------------------------------------
# claude.ai (static headers are a limited beta) and ChatGPT (OAuth or none) do not
# let a custom connector send a fixed token, so the endpoint lives at a secret
# path: /mcp/<token>. The full URL is the secret. No OAuth for now.

_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,}$")
_TOKEN_HELP = 'Generate one with: python3 -c "import secrets; print(secrets.token_urlsafe(32))"'


@server.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok"})


def path_token() -> str:
    token = os.environ.get("STEP_BY_STEP_MATH_PATH_TOKEN", "").strip()
    if not _TOKEN_PATTERN.match(token):
        raise SystemExit(
            "STEP_BY_STEP_MATH_PATH_TOKEN must be set to at least 32 URL-safe characters "
            f"(A-Z, a-z, 0-9, -, _) when the transport is http. {_TOKEN_HELP}"
        )
    return token


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
    token = path_token()
    port = int(os.environ.get("PORT", "8000"))
    # access_log=False: the request path contains the token and must not reach the logs.
    uvicorn.run(http_app(token), host="0.0.0.0", port=port, access_log=False, log_level="info")


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
        server.run("stdio")
    else:
        run_http()


if __name__ == "__main__":
    main()
