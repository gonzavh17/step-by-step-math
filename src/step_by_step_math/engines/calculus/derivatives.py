"""Derivatives engine (Calculus I). Pure functions, no I/O."""

import sympy as sp


def differentiate(expr: sp.Expr, variable: sp.Symbol) -> sp.Expr:
    """Derivative of `expr` with respect to `variable`, as SymPy returns it (not rewritten)."""
    return sp.diff(expr, variable)
