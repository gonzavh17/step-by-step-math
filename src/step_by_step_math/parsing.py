"""Safe parsing of math expressions written by the user or the model.

Shared by every engine. Never uses `eval` or `sympify` on free text:
`parse_expr` runs with a closed namespace (no builtins) and a function whitelist.
"""

import re
from tokenize import TokenError

import sympy as sp
from sympy.core.function import AppliedUndef
from sympy.parsing.sympy_parser import (
    convert_xor,
    parse_expr,
    standard_transformations,
)

MAX_EXPRESSION_LENGTH = 200
MAX_VARIABLE_LENGTH = 10

SYNTAX_HELP = "Use SymPy syntax: x**2, 3*x, sin(x), exp(x), log(x), sqrt(x)."


class InputError(ValueError):
    """Invalid input. The message is short and safe to show to the model."""


# Allowed functions and constants. Includes Argentine notation aliases.
FUNCTIONS: dict[str, object] = {
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
    "cot": sp.cot, "sec": sp.sec, "csc": sp.csc,
    "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
    "arcsin": sp.asin, "arccos": sp.acos, "arctan": sp.atan,
    "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh,
    "exp": sp.exp, "log": sp.log, "sqrt": sp.sqrt, "Abs": sp.Abs, "abs": sp.Abs,
    # Argentine aliases
    "sen": sp.sin, "tg": sp.tan, "ln": sp.log,
    "arcsen": sp.asin, "arctg": sp.atan,
    "senh": sp.sinh, "tgh": sp.tanh,
}
CONSTANTS: dict[str, object] = {"pi": sp.pi, "E": sp.E, "e": sp.E}

# Names `parse_expr` needs to build numbers and symbols.
_INTERNALS: dict[str, object] = {
    "Symbol": sp.Symbol, "Integer": sp.Integer, "Float": sp.Float,
    "Rational": sp.Rational, "Function": sp.Function,
}

RESERVED_NAMES = frozenset(FUNCTIONS) | frozenset(CONSTANTS) | frozenset(_INTERNALS)

# No underscores (blocks dunders), quotes, brackets, braces or ':'.
_VALID_CHARS = re.compile(r"^[A-Za-z0-9+\-*/^().,\s]+$")
_VALID_VARIABLE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
_TRANSFORMATIONS = standard_transformations + (convert_xor,)


def parse_expression(text: str) -> sp.Expr:
    """Turn text into a SymPy expression or raise InputError."""
    text = (text or "").strip()
    if not text:
        raise InputError(f"The expression is empty. {SYNTAX_HELP}")
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise InputError(
            f"The expression is too long (max {MAX_EXPRESSION_LENGTH} characters)."
        )
    if not _VALID_CHARS.match(text):
        raise InputError(f"The expression has disallowed characters. {SYNTAX_HELP}")

    namespace = {"__builtins__": {}, **_INTERNALS, **FUNCTIONS, **CONSTANTS}
    try:
        expr = parse_expr(
            text,
            local_dict={},
            global_dict=namespace,
            transformations=_TRANSFORMATIONS,
            evaluate=True,
        )
    except (SyntaxError, TokenError, TypeError, ValueError, AttributeError, NameError):
        raise InputError(f"Could not parse '{text}'. {SYNTAX_HELP}") from None

    if not isinstance(expr, sp.Expr):
        raise InputError(f"'{text}' is not a math expression. {SYNTAX_HELP}")

    unknown = sorted({str(f.func) for f in expr.atoms(AppliedUndef)})
    if unknown:
        raise InputError(
            f"Unknown function: {', '.join(unknown)}. "
            "Allowed: sin/sen, cos, tan/tg, exp, log/ln, sqrt, asin, acos, atan, sinh, cosh, tanh, Abs."
        )
    return expr


def parse_variable(name: str) -> sp.Symbol:
    """Validate the variable name (x, t, theta) and return its symbol."""
    name = (name or "").strip()
    if not _VALID_VARIABLE.match(name) or len(name) > MAX_VARIABLE_LENGTH:
        raise InputError(f"Invalid variable: '{name}'. Use a simple name like x, t or theta.")
    if name in RESERVED_NAMES:
        raise InputError(f"'{name}' is a reserved name; use another variable (x, t, ...).")
    return sp.Symbol(name)
