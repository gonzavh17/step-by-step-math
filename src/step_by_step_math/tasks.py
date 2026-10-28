"""Units of work that run inside the sandbox: parse -> engine -> plain dict.

They take and return plain data (strings, dicts) so they cross the process
boundary cheaply. Parsing happens here too because it can also hang
(e.g. 9**9**9**9 is evaluated while parsing). No I/O.
"""

from typing import Any

import sympy as sp

from step_by_step_math.engines.calculus.derivatives import differentiate
from step_by_step_math.engines.calculus.integrals import (
    Verification,
    definite_integral,
    verify_antiderivative,
)
from step_by_step_math.engines.calculus.integration_steps import definite_step, integrate_with_steps
from step_by_step_math.parsing import InputError, parse_bound, parse_expression, parse_variable
from step_by_step_math.steps import PALETTE

INCONCLUSIVE_NOTE = (
    "Numerically it looks correct (the difference is ~0 at several points), "
    "but SymPy could not prove it symbolically."
)


def _latex(expr: sp.Expr) -> str:
    return sp.latex(expr, ln_notation=True)


def _constant_name(*exprs: sp.Expr) -> str:
    used = {s.name for e in exprs for s in e.free_symbols}
    return next(name for name in ("C", "K", "C_1") if name not in used)


def differentiate_task(expression: str, variable: str) -> dict[str, Any]:
    expr = parse_expression(expression)
    x = parse_variable(variable)
    derivative = differentiate(expr, x)
    return {"result": sp.sstr(derivative), "latex": _latex(derivative), "variable": x.name}


METHODS = ("auto", "parts", "substitution", "partial_fractions")


def integrate_task(
    expression: str,
    variable: str,
    lower: str | None,
    upper: str | None,
    method: str = "auto",
    u: str | None = None,
    dv: str | None = None,
) -> dict[str, Any]:
    """Solve the integral step by step. The "board" key holds the steps for the whiteboard."""
    f = parse_expression(expression)
    x = parse_variable(variable)
    if (lower is None) != (upper is None):
        raise InputError("Give both limits (lower and upper) for a definite integral, or neither.")
    if method not in METHODS:
        raise InputError(f"Unknown method '{method}'. Use one of: {', '.join(METHODS)}.")
    if u is not None and method not in ("parts", "substitution"):
        raise InputError("u only applies to method 'parts' or 'substitution'.")
    if dv is not None and method != "parts":
        raise InputError("dv only applies to method 'parts'.")
    u_expr = parse_expression(u) if u is not None else None
    dv_expr = parse_expression(dv) if dv is not None else None

    definite = lower is not None
    c = _constant_name(f, *(e for e in (u_expr, dv_expr) if e is not None))
    solved = integrate_with_steps(f, x, method, u_expr, dv_expr, constant=None if definite else c)  # type: ignore[arg-type]
    F = solved.antiderivative
    steps = list(solved.steps)
    out: dict[str, Any] = {"kind": "definite" if definite else "indefinite", "method": method}

    if not definite:
        problem = sp.Integral(f, x)
        out["result"] = f"{sp.sstr(F)} + {c}"
        out["latex"] = f"{_latex(F)} + {c}"
        out["verification"] = solved.verification
        board_result = out["latex"]
    else:
        a, b = parse_bound(lower), parse_bound(upper)
        problem = sp.Integral(f, (x, a, b))
        integral = definite_integral(f, x, a, b)
        steps.append(definite_step(F, x, a, b, integral))
        out["status"] = integral.status
        out["result"] = sp.sstr(integral.value) if integral.value is not None else None
        out["latex"] = _latex(integral.value) if integral.value is not None else None
        out["verification"] = (
            "verified" if solved.verification == "verified" and integral.verification.status == "verified"
            else "inconclusive"
        )
        out["improper"] = integral.improper
        if integral.discontinuities:
            out["discontinuities"] = [sp.sstr(p) for p in integral.discontinuities]
        if integral.explanation:
            out["explanation"] = integral.explanation
        if integral.warnings:
            out["warnings"] = integral.warnings
        board_result = out["latex"] if out["latex"] is not None else r"\text{diverge}"

    if solved.generic_fallback:
        out["generic_fallback"] = True
    if out["verification"] == "inconclusive":
        out.setdefault("warnings", []).append(INCONCLUSIVE_NOTE)
    out["steps"] = len(steps)
    out["board"] = {
        "problem": _latex(problem),
        "method": method,
        "steps": [step.to_dict() for step in steps],
        "palette": PALETTE,
        "result": board_result,
    }
    return out


def verify_task(integrand: str, antiderivative: str, variable: str) -> dict[str, Any]:
    f = parse_expression(integrand)
    F = parse_expression(antiderivative)
    x = parse_variable(variable)
    verification: Verification = verify_antiderivative(f, F, x)
    out: dict[str, Any] = {"status": verification.status}
    if verification.status != "verified":
        out["difference"] = sp.sstr(verification.difference)
        out["difference_latex"] = _latex(verification.difference)
    if verification.status == "inconclusive":
        out["note"] = INCONCLUSIVE_NOTE
    elif verification.status == "incorrect":
        out["note"] = "d/dx(antiderivative) - integrand is not 0: the antiderivative is wrong."
    return out
