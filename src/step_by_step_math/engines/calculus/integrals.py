"""Integrals engine (Calculus I). Pure functions, no I/O.

- Antiderivatives come from `manualintegrate`, which gives textbook-style forms.
  `integrate()` is only a fallback, and the result says so.
- Every antiderivative is checked by differentiating it.
- Definite integrals look for discontinuities before applying Barrow's rule;
  improper integrals are computed with one-sided limits of the antiderivative.
"""

from dataclasses import dataclass, field
from typing import Literal

import sympy as sp
from sympy.calculus.util import continuous_domain
from sympy.integrals.manualintegrate import manualintegrate

from step_by_step_math.errors import UserFacingError

Method = Literal["manualintegrate", "integrate_fallback"]
VerificationStatus = Literal["verified", "inconclusive", "incorrect"]

# Points used for the numeric check. Irregular on purpose, to avoid special values.
_SAMPLE_POINTS = ("0.3137", "0.7291", "1.1853", "2.4217", "-0.4421", "-1.3089", "3.7713", "-2.9131")
_MIN_VALID_SAMPLES = 3
_NUMERIC_DIGITS = 30
_NUMERIC_TOLERANCE = 1e-12
_DEFINITE_TOLERANCE = 1e-8


class IntegrationError(UserFacingError, ValueError):
    """The integral could not be computed or checked reliably."""


@dataclass(frozen=True)
class Antiderivative:
    expr: sp.Expr
    method: Method


@dataclass(frozen=True)
class Verification:
    status: VerificationStatus
    difference: sp.Expr  # simplify(diff(F) - f); 0 when verified


@dataclass(frozen=True)
class IndefiniteIntegral:
    antiderivative: Antiderivative
    verification: Verification


@dataclass(frozen=True)
class DefiniteIntegral:
    status: Literal["converges", "diverges"]
    value: sp.Expr | None  # None when it diverges
    method: Method
    verification: Verification  # of the antiderivative used for Barrow / limits
    improper: bool
    discontinuities: list[sp.Expr] = field(default_factory=list)
    explanation: str = ""  # why it diverges
    warnings: list[str] = field(default_factory=list)


# --- Verification -------------------------------------------------------------

def verify_antiderivative(integrand: sp.Expr, antiderivative: sp.Expr, x: sp.Symbol) -> Verification:
    """Check that d/dx antiderivative == integrand.

    verified:     simplify(diff(F) - f) == 0.
    inconclusive: SymPy could not prove it, but the difference is ~0 at every sample point.
    incorrect:    otherwise.
    """
    derivative = _drop_step_derivatives(sp.diff(antiderivative, x))
    difference = sp.simplify(derivative - integrand)
    if difference == 0:
        return Verification("verified", sp.Integer(0))
    if _numerically_zero(difference, integrand, x):
        return Verification("inconclusive", difference)
    return Verification("incorrect", difference)


def _drop_step_derivatives(expr: sp.Expr) -> sp.Expr:
    """d/dx floor(...) and ceiling(...) are 0 almost everywhere; SymPy leaves them unevaluated.

    integrate() adds floor() terms to make some antiderivatives continuous
    (e.g. 1/(2 + cos(x))).
    """
    return expr.replace(
        lambda e: isinstance(e, (sp.Derivative, sp.Subs)) and e.has(sp.floor, sp.ceiling),
        lambda e: sp.Integer(0),
    )


def _numerically_zero(difference: sp.Expr, integrand: sp.Expr, x: sp.Symbol) -> bool:
    # Other symbols (parameters like a, k) get fixed irregular values too.
    params = sorted(difference.free_symbols - {x}, key=str)
    param_values = {p: sp.Float(1.6180339 + 0.37 * i) for i, p in enumerate(params)}

    valid = 0
    for point in _SAMPLE_POINTS:
        values = {x: sp.Float(point), **param_values}
        try:
            d = complex(difference.evalf(_NUMERIC_DIGITS, subs=values))
            f = complex(integrand.evalf(_NUMERIC_DIGITS, subs=values))
        except (TypeError, ValueError):
            continue  # zoo, unevaluated, ...
        if not all(map(_is_finite, (d, f))):
            continue  # outside the domain at this point
        if abs(d) > _NUMERIC_TOLERANCE * (1 + abs(f)):
            return False
        valid += 1
    return valid >= _MIN_VALID_SAMPLES


def _is_finite(z: complex) -> bool:
    return z == z and abs(z) != float("inf")


# --- Indefinite integrals ----------------------------------------------------

def find_antiderivative(integrand: sp.Expr, x: sp.Symbol) -> Antiderivative:
    """Antiderivative via manualintegrate, falling back to integrate()."""
    try:
        result = manualintegrate(integrand, x)
    except Exception:  # noqa: BLE001 - any internal failure means "try the fallback"
        result = None
    if result is not None and not result.has(sp.Integral):
        return Antiderivative(result, "manualintegrate")

    result = sp.integrate(integrand, x)
    if result.has(sp.Integral):
        raise IntegrationError(
            f"SymPy could not find an antiderivative of {sp.sstr(integrand)}. "
            "It may not have an elementary antiderivative."
        )
    return Antiderivative(result, "integrate_fallback")


def indefinite_integral(integrand: sp.Expr, x: sp.Symbol) -> IndefiniteIntegral:
    """Antiderivative (without + C), checked by differentiation."""
    antiderivative = find_antiderivative(integrand, x)
    verification = verify_antiderivative(integrand, antiderivative.expr, x)
    _reject_incorrect(verification)
    return IndefiniteIntegral(antiderivative, verification)


def _reject_incorrect(verification: Verification) -> None:
    # The engine never returns a result it could not check.
    if verification.status == "incorrect":
        raise IntegrationError(
            "The antiderivative found did not pass the derivative check, so it is not shown."
        )


# --- Definite integrals --------------------------------------------------------

def definite_integral(integrand: sp.Expr, x: sp.Symbol, lower: sp.Expr, upper: sp.Expr) -> DefiniteIntegral:
    """Integral of `integrand` from `lower` to `upper`.

    Without discontinuities in [lower, upper] and with finite limits: Barrow's rule.
    Otherwise it is improper: split at the discontinuities and use one-sided limits
    of the antiderivative. If any limit is not finite, the integral diverges.
    """
    if lower == upper:
        return DefiniteIntegral("converges", sp.Integer(0), "manualintegrate",
                                Verification("verified", sp.Integer(0)), improper=False)

    order = upper > lower
    if order not in (sp.true, sp.false):
        raise IntegrationError("Could not compare the integration limits; use real constants.")
    sign = 1 if order is sp.true else -1
    a, b = (lower, upper) if sign == 1 else (upper, lower)

    antiderivative = find_antiderivative(integrand, x)
    verification = verify_antiderivative(integrand, antiderivative.expr, x)
    _reject_incorrect(verification)
    F = antiderivative.expr

    warnings: list[str] = []
    if verification.status == "inconclusive":
        warnings.append("The antiderivative passed a numeric check but could not be verified symbolically.")

    discontinuities = _discontinuities(integrand, x, a, b)
    if discontinuities is None:
        return _fallback_definite(integrand, x, lower, upper, verification, warnings + [
            "Could not determine where the integrand is continuous; computed with integrate() instead of Barrow's rule."
        ])

    improper = bool(discontinuities) or a.is_infinite or b.is_infinite
    if discontinuities:
        points = ", ".join(sp.sstr(p) for p in discontinuities)
        warnings.append(
            f"The integrand is not continuous (or not defined) at x = {points} in [{sp.sstr(a)}, {sp.sstr(b)}], "
            "so Barrow's rule does not apply directly: computed as an improper integral "
            "with one-sided limits."
        )

    if not improper:
        value = sp.simplify(F.subs(x, b) - F.subs(x, a))
    else:
        interior = [p for p in discontinuities if p != a and p != b]
        value, explanation = _improper_value(F, x, [a, *interior, b], set(discontinuities))
        if value is None:
            return DefiniteIntegral("diverges", None, antiderivative.method, verification,
                                    improper=True, discontinuities=discontinuities,
                                    explanation=explanation, warnings=warnings)

    value = sp.simplify(sign * value)
    if not _matches_numeric(integrand, x, lower, upper, value) and not _matches_integrate(
        integrand, x, lower, upper, value
    ):
        return _fallback_definite(integrand, x, lower, upper, verification, warnings + [
            "The value from the antiderivative did not match a numeric check; computed with integrate() instead."
        ], improper=improper, discontinuities=discontinuities)

    if value.is_real is False:
        warnings.append(
            "The result is not a real number: SymPy uses principal (complex) roots, so e.g. "
            "(x - 1)**(1/3) is complex for x < 1. For a real cube root of a negative base, "
            "rewrite the integrand on that part of the interval."
        )
    return DefiniteIntegral("converges", value, antiderivative.method, verification,
                            improper=improper, discontinuities=discontinuities, warnings=warnings)


def _discontinuities(f: sp.Expr, x: sp.Symbol, a: sp.Expr, b: sp.Expr) -> list[sp.Expr] | None:
    """Points of [a, b] where f is not continuous, sorted. None if SymPy cannot tell."""
    interval = sp.Interval(a, b)
    try:
        continuous = continuous_domain(f, x, interval)
    except Exception:  # noqa: BLE001
        return None
    missing = interval - continuous
    if missing is sp.S.EmptySet:
        return []
    if not isinstance(missing, sp.FiniteSet):
        return None  # infinitely many points or an interval: out of scope
    return sorted(missing, key=lambda p: float(p))


def _improper_value(
    F: sp.Expr, x: sp.Symbol, breakpoints: list[sp.Expr], singular: set[sp.Expr]
) -> tuple[sp.Expr | None, str]:
    """Sum F(q-) - F(p+) over each piece [p, q]. (None, explanation) if it diverges."""
    total = sp.Integer(0)
    for p, q in zip(breakpoints, breakpoints[1:]):
        left = _endpoint_value(F, x, p, "+", p in singular)
        right = _endpoint_value(F, x, q, "-", q in singular)
        for point, direction, value in ((p, "+", left), (q, "-", right)):
            if not _is_finite_value(value):
                return None, _divergence_explanation(F, x, point, direction, value)
        total += right - left
    return total, ""


def _endpoint_value(F: sp.Expr, x: sp.Symbol, point: sp.Expr, direction: str, singular: bool) -> sp.Expr:
    if point.is_infinite:
        return sp.limit(F, x, point)
    if singular:
        return sp.limit(F, x, point, direction)
    return F.subs(x, point)


def _is_finite_value(value: sp.Expr) -> bool:
    return (
        value.is_finite is True
        and not value.has(sp.AccumBounds, sp.Limit, sp.nan, sp.zoo, sp.oo, -sp.oo)
    )


def _divergence_explanation(F: sp.Expr, x: sp.Symbol, point: sp.Expr, direction: str, value: sp.Expr) -> str:
    where = f"x -> {sp.sstr(point)}" if point.is_infinite else f"x -> {sp.sstr(point)}{direction}"
    if value.has(sp.AccumBounds):
        behavior = "oscillates and has no limit"
    elif value in (sp.oo, -sp.oo, sp.zoo):
        behavior = f"tends to {sp.sstr(value)}"
    else:
        behavior = f"has no finite limit ({sp.sstr(value)})"
    return f"The antiderivative {sp.sstr(F)} {behavior} as {where}, so the integral diverges."


def _matches_numeric(f: sp.Expr, x: sp.Symbol, lower: sp.Expr, upper: sp.Expr, value: sp.Expr) -> bool:
    """Compare against numeric quadrature. True if it cannot be checked (e.g. parameters)."""
    if value.free_symbols or f.free_symbols - {x}:
        return True
    try:
        numeric = complex(sp.Integral(f, (x, lower, upper)).evalf(15))
        exact = complex(value.evalf(15))
    except (TypeError, ValueError):
        return True
    if not (_is_finite(numeric) and _is_finite(exact)):
        return True
    return abs(numeric - exact) <= _DEFINITE_TOLERANCE * (1 + abs(exact))


def _matches_integrate(f: sp.Expr, x: sp.Symbol, lower: sp.Expr, upper: sp.Expr, value: sp.Expr) -> bool:
    """Second opinion when quadrature disagrees (it is unreliable on oscillating tails)."""
    other = sp.integrate(f, (x, lower, upper))
    return not other.has(sp.Integral) and sp.simplify(other - value) == 0


def _fallback_definite(
    f: sp.Expr, x: sp.Symbol, lower: sp.Expr, upper: sp.Expr, verification: Verification,
    warnings: list[str], improper: bool = False, discontinuities: list[sp.Expr] | None = None,
) -> DefiniteIntegral:
    value = sp.integrate(f, (x, lower, upper))
    discontinuities = discontinuities or []
    if value.has(sp.Integral):
        raise IntegrationError("SymPy could not compute this definite integral.")
    if not _is_finite_value(value):
        return DefiniteIntegral("diverges", None, "integrate_fallback", verification,
                                improper=True, discontinuities=discontinuities,
                                explanation=f"integrate() gives {sp.sstr(value)}, so the integral diverges.",
                                warnings=warnings)
    return DefiniteIntegral("converges", sp.simplify(value), "integrate_fallback", verification,
                            improper=improper, discontinuities=discontinuities, warnings=warnings)
