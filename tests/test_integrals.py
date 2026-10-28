import pytest
import sympy as sp

from step_by_step_math.engines.calculus.integrals import (
    IntegrationError,
    definite_integral,
    indefinite_integral,
    verify_antiderivative,
)
from step_by_step_math.parsing import parse_expression as P

x = sp.Symbol("x")


def check_textbook(text: str) -> None:
    f = P(text)
    integral = indefinite_integral(f, x)
    assert sp.simplify(sp.diff(integral.antiderivative.expr, x) - f) == 0
    assert integral.antiderivative.method == "manualintegrate"
    assert integral.verification.status == "verified"


# --- Indefinite ---------------------------------------------------------------

@pytest.mark.parametrize(
    "text", ["x**3", "1/x", "exp(x)", "cos(x)", "1/(1 + x**2)", "1/sqrt(1 - x**2)", "5", "sqrt(x)"]
)
def test_basic(text):
    check_textbook(text)


@pytest.mark.parametrize(
    "text", ["2*x*cos(x**2)", "x/(x**2 + 1)", "exp(3*x + 1)", "sin(x)**2*cos(x)", "log(x)/x"]
)
def test_substitution(text):
    check_textbook(text)


@pytest.mark.parametrize(
    "text", ["x*exp(x)", "x*sin(x)", "log(x)", "x**2*log(x)", "exp(x)*sin(x)", "atan(x)"]
)
def test_parts(text):
    check_textbook(text)


@pytest.mark.parametrize(
    "text", ["1/(x**2 - 1)", "(x + 3)/(x**2 - 3*x + 2)", "1/(x*(x + 1)**2)", "1/(x**2 + 2*x + 5)"]
)
def test_partial_fractions(text):
    check_textbook(text)


@pytest.mark.parametrize(
    "text", ["sin(x)**3", "sin(x)*cos(x)", "tan(x)", "cos(x)**2", "sin(x)**2*cos(x)**3", "sec(x)**2"]
)
def test_trigonometric(text):
    check_textbook(text)


def test_textbook_form():
    assert indefinite_integral(P("x*exp(x)"), x).antiderivative.expr == x * sp.exp(x) - sp.exp(x)


def test_fallback_is_marked():
    # manualintegrate cannot do this one (SymPy 1.14); integrate() can.
    integral = indefinite_integral(P("1/(2 + cos(x))"), x)
    assert integral.antiderivative.method == "integrate_fallback"
    assert integral.verification.status in ("verified", "inconclusive")


def test_no_elementary_antiderivative():
    with pytest.raises(IntegrationError, match="could not find an antiderivative"):
        indefinite_integral(P("x**x"), x)


# --- Definite -----------------------------------------------------------------

def definite(text, a, b):
    return definite_integral(P(text), x, P(a), P(b))


@pytest.mark.parametrize(
    "text, a, b, expected",
    [
        ("x**2", "0", "1", sp.Rational(1, 3)),
        ("sin(x)", "0", "pi", sp.Integer(2)),
        ("x*exp(x)", "0", "1", sp.Integer(1)),
        ("x**2", "1", "0", sp.Rational(-1, 3)),  # reversed limits
        ("x**2", "2", "2", sp.Integer(0)),
        ("1/(2 + cos(x))", "0", "2*pi", 2 * sp.pi / sp.sqrt(3)),
    ],
)
def test_definite_proper(text, a, b, expected):
    r = definite(text, a, b)
    assert r.status == "converges"
    assert not r.improper
    assert sp.simplify(r.value - expected) == 0


@pytest.mark.parametrize(
    "text, a, b, expected",
    [
        ("exp(-x)", "0", "oo", sp.Integer(1)),
        ("1/(1 + x**2)", "-oo", "oo", sp.pi),
        ("1/x**2", "1", "oo", sp.Integer(1)),
        ("sin(x)/x", "0", "oo", sp.pi / 2),
    ],
)
def test_improper_infinite_limits(text, a, b, expected):
    r = definite(text, a, b)
    assert r.status == "converges" and r.improper
    assert sp.simplify(r.value - expected) == 0


@pytest.mark.parametrize(
    "text, a, b, expected, points",
    [
        ("1/sqrt(x)", "0", "1", sp.Integer(2), [0]),
        ("log(x)", "0", "1", sp.Integer(-1), [0]),
        ("log(x**2)", "-1", "1", sp.Integer(-4), [0]),  # interior point
        ("1/sqrt(1 - x**2)", "-1", "1", sp.pi, [-1, 1]),  # both endpoints
    ],
)
def test_improper_discontinuity_converges(text, a, b, expected, points):
    r = definite(text, a, b)
    assert r.status == "converges" and r.improper
    assert r.discontinuities == points
    assert any("Barrow" in w for w in r.warnings)
    assert sp.simplify(r.value - expected) == 0


def test_non_real_result_is_flagged():
    # SymPy's (x - 1)**(1/3) is the principal (complex) root for x < 1.
    r = definite("1/(x - 1)**(1/3)", "0", "2")
    assert any("not a real number" in w for w in r.warnings)


@pytest.mark.parametrize(
    "text, a, b, point",
    [
        ("1/x", "-1", "1", 0),
        # Classic trap: Barrow would give -2 here.
        ("1/x**2", "-1", "1", 0),
        ("tan(x)", "0", "2", sp.pi / 2),
    ],
)
def test_discontinuity_diverges(text, a, b, point):
    r = definite(text, a, b)
    assert r.status == "diverges"
    assert r.value is None
    assert r.discontinuities == [point]
    assert "diverges" in r.explanation
    assert any("Barrow" in w for w in r.warnings)


def test_infinite_limit_diverges():
    r = definite("1/x", "1", "oo")
    assert r.status == "diverges"
    assert "oo" in r.explanation


def test_oscillating_diverges():
    r = definite("sin(x)", "0", "oo")
    assert r.status == "diverges"
    assert "oscillates" in r.explanation


# --- verify_antiderivative ------------------------------------------------------

@pytest.mark.parametrize(
    "integrand, antiderivative",
    [
        ("2*x", "x**2"),
        ("2*x", "x**2 + 7"),
        ("2*x", "x**2 + C"),
        # Differ by a constant
        ("sin(x)*cos(x)", "sin(x)**2/2"),
        ("sin(x)*cos(x)", "-cos(x)**2/2"),
        ("sin(x)*cos(x)", "-cos(2*x)/4"),
        # Differ by a trigonometric identity
        ("tan(x)**2", "sin(x)/cos(x) - x"),
        ("1/cos(x)**2", "sin(x)/cos(x)"),
        ("2*sin(x)*cos(x)", "1 - cos(x)**2"),
        ("x*exp(x)", "(x - 1)*exp(x)"),
    ],
)
def test_verify_correct(integrand, antiderivative):
    assert verify_antiderivative(P(integrand), P(antiderivative), x).status == "verified"


@pytest.mark.parametrize(
    "integrand, antiderivative, difference",
    [
        ("x", "x**2", x),
        ("x*exp(x)", "x*exp(x) + exp(x)", 2 * sp.exp(x)),
        ("cos(x)", "-sin(x)", -2 * sp.cos(x)),
        ("1/x", "log(x)/x", None),
    ],
)
def test_verify_incorrect(integrand, antiderivative, difference):
    v = verify_antiderivative(P(integrand), P(antiderivative), x)
    assert v.status == "incorrect"
    assert v.difference != 0
    if difference is not None:
        assert sp.simplify(v.difference - difference) == 0


def test_verify_inconclusive():
    # ln(tan(x/2 + pi/4)) is a valid antiderivative of sec(x), but simplify cannot prove it.
    v = verify_antiderivative(P("1/cos(x)"), P("log(tan(x/2 + pi/4))"), x)
    assert v.status == "inconclusive"
