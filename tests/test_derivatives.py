import pytest
import sympy as sp

from step_by_step_math.engines.calculus.derivatives import differentiate
from step_by_step_math.parsing import (
    MAX_EXPRESSION_LENGTH,
    InputError,
    parse_expression,
    parse_variable,
)

x, t = sp.symbols("x t")


def d(text: str, var: str = "x") -> sp.Expr:
    return differentiate(parse_expression(text), parse_variable(var))


def equal(a: sp.Expr, b: sp.Expr) -> bool:
    return sp.simplify(a - b) == 0


# --- Typical cases ------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        # Polynomials
        ("x**3 - 4*x**2 + 7*x - 2", 3 * x**2 - 8 * x + 7),
        ("x^5", 5 * x**4),
        ("5", sp.Integer(0)),
        # Product
        ("x**2*sin(x)", 2 * x * sp.sin(x) + x**2 * sp.cos(x)),
        ("x*exp(x)", sp.exp(x) + x * sp.exp(x)),
        # Quotient
        ("sin(x)/x", (x * sp.cos(x) - sp.sin(x)) / x**2),
        # Chain rule
        ("sin(x**2)", 2 * x * sp.cos(x**2)),
        ("(3*x + 1)**4", 12 * (3 * x + 1) ** 3),
        ("exp(sin(x))", sp.cos(x) * sp.exp(sp.sin(x))),
        ("sqrt(1 - x**2)", -x / sp.sqrt(1 - x**2)),
        # Trigonometric
        ("cos(x)", -sp.sin(x)),
        ("tan(x)", 1 / sp.cos(x) ** 2),
        ("atan(x)", 1 / (1 + x**2)),
        # Exponential and logarithm
        ("exp(2*x)", 2 * sp.exp(2 * x)),
        ("log(x)", 1 / x),
        ("log(x**2 + 1)", 2 * x / (x**2 + 1)),
        ("2**x", 2**x * sp.log(2)),
        ("E**x", sp.exp(x)),
    ],
)
def test_typical_cases(text, expected):
    assert equal(d(text), expected)


def test_other_variable():
    assert equal(d("t**2 + x*t", "t"), 2 * t + x)


def test_symbolic_constants():
    # a is a constant with respect to x
    a = sp.Symbol("a")
    assert equal(d("a*x**2"), 2 * a * x)


# --- Argentine notation aliases -----------------------------------------------

@pytest.mark.parametrize(
    "alias, standard",
    [
        ("sen(x)", "sin(x)"),
        ("tg(x)", "tan(x)"),
        ("ln(x)", "log(x)"),
        ("arcsen(x)", "asin(x)"),
        ("arctg(x)", "atan(x)"),
        ("sen(x)**2 + ln(tg(x))", "sin(x)**2 + log(tan(x))"),
    ],
)
def test_argentine_aliases(alias, standard):
    assert parse_expression(alias) == parse_expression(standard)


def test_derivative_with_alias():
    assert equal(d("sen(x)*ln(x)"), sp.cos(x) * sp.log(x) + sp.sin(x) / x)


# --- Invalid input ------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "x**",
        "sin(x",
        "x +* 2",
        "__import__('os')",
        "x.__class__",
        "[x, 1]",
        "lambda: 1",
        "x; 2",
        "x == 2",
        "x" * (MAX_EXPRESSION_LENGTH + 1),
    ],
)
def test_invalid_expression(text):
    with pytest.raises(InputError):
        parse_expression(text)


def test_unknown_function():
    with pytest.raises(InputError, match="Unknown function: foo"):
        parse_expression("foo(x)")


def test_actionable_message():
    with pytest.raises(InputError, match="SymPy syntax"):
        parse_expression("x**")


@pytest.mark.parametrize("name", ["", "2x", "x y", "x_1", "sin", "pi", "a" * 20])
def test_invalid_variable(name):
    with pytest.raises(InputError):
        parse_variable(name)
