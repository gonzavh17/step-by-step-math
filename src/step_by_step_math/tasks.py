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
    indefinite_integral,
    verify_antiderivative,
)
from step_by_step_math.parsing import InputError, parse_bound, parse_expression, parse_variable

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


def integrate_task(expression: str, variable: str, lower: str | None, upper: str | None) -> dict[str, Any]:
    f = parse_expression(expression)
    x = parse_variable(variable)
    if (lower is None) != (upper is None):
        raise InputError("Give both limits (lower and upper) for a definite integral, or neither.")

    if lower is None:
        integral = indefinite_integral(f, x)
        F = integral.antiderivative.expr
        c = _constant_name(f, F)
        out: dict[str, Any] = {
            "kind": "indefinite",
            "result": f"{sp.sstr(F)} + {c}",
            "latex": f"{_latex(F)} + {c}",
            "method": integral.antiderivative.method,
            "verification": integral.verification.status,
        }
        if integral.verification.status == "inconclusive":
            out["warnings"] = [INCONCLUSIVE_NOTE]
        return out

    a, b = parse_bound(lower), parse_bound(upper)
    integral = definite_integral(f, x, a, b)
    out = {
        "kind": "definite",
        "status": integral.status,
        "result": sp.sstr(integral.value) if integral.value is not None else None,
        "latex": _latex(integral.value) if integral.value is not None else None,
        "method": integral.method,
        "verification": integral.verification.status,
        "improper": integral.improper,
    }
    if integral.discontinuities:
        out["discontinuities"] = [sp.sstr(p) for p in integral.discontinuities]
    if integral.explanation:
        out["explanation"] = integral.explanation
    if integral.warnings:
        out["warnings"] = integral.warnings
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
