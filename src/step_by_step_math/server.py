"""MCP server. Thin layer: validates input, calls the engine and adapts the response."""

from typing import TypedDict

import sympy as sp
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from step_by_step_math.engines.calculus.derivatives import differentiate as engine_differentiate
from step_by_step_math.parsing import InputError, parse_expression, parse_variable

server = MCPServer(
    name="step-by-step-math",
    instructions=(
        "Symbolic math engine (SymPy). Never compute by hand: "
        "use these tools for every calculation and show their result as is."
    ),
)


class DerivativeResult(TypedDict):
    result: str  # SymPy syntax, reusable as input
    latex: str
    variable: str


@server.tool(
    description=(
        "Differentiate an expression with respect to a variable using a symbolic engine (SymPy). "
        "ALWAYS use it when a derivative is needed: do not differentiate by hand or adjust the result. "
        "'expression' syntax (SymPy): x**2 (or x^2), 3*x (explicit multiplication), "
        "sin(x), cos(x), tan(x), exp(x), log(x) (natural log), sqrt(x), asin(x), atan(x). "
        "Also accepts sen, tg and ln. Constants: pi, E. "
        "Returns the result in SymPy syntax and in LaTeX."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
)
def differentiate(expression: str, variable: str = "x") -> DerivativeResult:
    try:
        expr = parse_expression(expression)
        var = parse_variable(variable)
    except InputError as e:
        raise ToolError(str(e)) from None

    derivative = engine_differentiate(expr, var)
    return {
        "result": sp.sstr(derivative),
        "latex": sp.latex(derivative, ln_notation=True),
        "variable": var.name,
    }


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
