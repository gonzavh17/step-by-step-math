"""Step-by-step integration (Calculus I). Pure functions, no I/O.

The board follows a *state*: the whole expression, with the integrals still to
solve left as unevaluated `Integral` objects, e.g. `x*exp(x) - Integral(exp(x), x)`.
Each step replaces one of those integrals (one transformation per step) and is
checked before it is accepted:

- local check: d/dw(replacement) == integrand of the replaced integral, where
  SymPy differentiates any remaining `Integral(g, w)` to `g`;
- rule-specific checks where that does not apply (substitution, solving for I).

A step that fails its check stops everything: no unchecked step is ever shown.
The last two steps are always the constant of integration and the derivative check.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import sympy as sp
from sympy.integrals.manualintegrate import (
    AddRule,
    AlternativeRule,
    CompleteSquareRule,
    ConstantTimesRule,
    CyclicPartsRule,
    DontKnowRule,
    PartsRule,
    RewriteRule,
    Rule,
    URule,
    integral_steps,
)

from step_by_step_math.engines.calculus.integrals import (
    DefiniteIntegral,
    IntegrationError,
    _drop_step_derivatives,
    _numerically_zero,
    find_antiderivative,
    verify_antiderivative,
)
from step_by_step_math.steps import (
    Highlight,
    Step,
    colored,
    factor_tex,
    integral_tex,
    paren,
    tex,
    tex_marking,
    tex_with_part,
)

StepMethod = Literal["auto", "parts", "substitution", "partial_fractions"]
_CheckStatus = Literal["symbolic", "numeric", "failed"]

# Names for the unknown constants in partial fractions (skips E and I: SymPy constants).
_CONSTANT_NAMES = "ABCDFGHJKLMNPQRSTVW"


@dataclass(frozen=True)
class StepByStep:
    steps: list[Step]
    antiderivative: sp.Expr  # without + C
    method: StepMethod
    generic_fallback: bool  # some integral had no textbook steps (integrate() was used)
    verification: Literal["verified", "inconclusive"]


# --- Checks -------------------------------------------------------------------------

def _zero_status(expr: sp.Expr, w: sp.Symbol) -> _CheckStatus:
    if expr == 0:
        return "symbolic"
    try:
        if sp.simplify(expr) == 0:
            return "symbolic"
    except Exception:  # noqa: BLE001 - simplify can fail on odd inputs; try numerically
        pass
    return "numeric" if _numerically_zero(expr, sp.Integer(1), w) else "failed"


def _antiderivative_status(replacement: sp.Expr, integrand: sp.Expr, w: sp.Symbol) -> _CheckStatus:
    # diff(Integral(g, w), w) == g, so pending integrals in `replacement` are fine.
    derivative = _drop_step_derivatives(sp.diff(replacement, w))
    return _zero_status(derivative - integrand, w)


# --- Builder ------------------------------------------------------------------------

class _Builder:
    def __init__(self, problem: sp.Integral):
        self.state: sp.Expr = problem
        self.steps: list[Step] = []
        self.generic = False
        self.numeric_only = False

    def _record(self, before: str, after: str, rule: str, note: str, status: _CheckStatus,
                aux: Mapping[str, str] | None, highlight: list[Highlight] | None) -> None:
        if status == "failed":
            raise IntegrationError(f"Internal check failed at step '{rule}', so no steps are shown.")
        if status == "numeric":
            self.numeric_only = True
        self.steps.append(Step(before=before, after=after, rule=rule, note=note,
                               highlight=list(highlight or []), aux=dict(aux or {}),
                               verified=status == "symbolic"))

    def transform(self, target: sp.Expr, replacement: sp.Expr, rule: str, note: str, *,
                  before_part: str | None = None, after_part: str | None = None,
                  aux: Mapping[str, str] | None = None, highlight: list[Highlight] | None = None,
                  status: _CheckStatus | None = None) -> bool:
        """Replace `target` (an Integral in the state) by `replacement`. False if it is gone."""
        if not self.state.has(target):
            return False  # the same integral appeared twice and was already solved
        if replacement == target:
            return True  # nothing to show
        if status is None:
            assert isinstance(target, sp.Integral)
            status = _antiderivative_status(replacement, target.function, target.variables[0])
        new_state = self.state.xreplace({target: replacement})
        before = _render(self.state, target, before_part)
        after = _render(new_state, replacement, after_part)
        self._record(before, after, rule, note, status, aux, highlight)
        self.state = new_state
        return True

    def replace_state(self, new_state: sp.Expr, rule: str, note: str, *, before: str, after: str,
                      status: _CheckStatus, aux: Mapping[str, str] | None = None,
                      highlight: list[Highlight] | None = None) -> None:
        self._record(before, after, rule, note, status, aux, highlight)
        self.state = new_state

    def side_step(self, before: str, after: str, rule: str, note: str, status: _CheckStatus,
                  aux: Mapping[str, str] | None = None, highlight: list[Highlight] | None = None) -> None:
        """A step that shows a side computation and does not change the state."""
        if before == after:
            return  # e.g. a denominator that is already factored
        self._record(before, after, rule, note, status, aux, highlight)


def _render(state: sp.Expr, target: sp.Expr, part: str | None) -> str:
    """LaTeX of the state, with `target` printed as the custom `part` if possible."""
    if part is None:
        return tex(state)
    # If SymPy reshaped the expression or `target` repeats, fall back to plain LaTeX.
    return tex_with_part(state, target, part) or tex(state)


# --- Auto mode: integral_steps tree -> steps ------------------------------------

_ATOMIC_NOTES: dict[str, tuple[str, str]] = {
    "ConstantRule": ("constant", r"Integral de una constante: \(\int c\,dx = c\,x\)"),
    "PowerRule": ("power", r"Regla de la potencia: \(\int x^n\,dx = \frac{x^{n+1}}{n+1}\)"),
    "NestedPowRule": ("power", r"Regla de la potencia"),
    "ReciprocalRule": ("reciprocal", r"Inmediata: \(\int \frac{1}{x}\,dx = \ln x\)"),
    "SinRule": ("trig", r"Inmediata: \(\int \sin x\,dx = -\cos x\)"),
    "CosRule": ("trig", r"Inmediata: \(\int \cos x\,dx = \sin x\)"),
    "Sec2Rule": ("trig", r"Inmediata: \(\int \sec^2 x\,dx = \tan x\)"),
    "Csc2Rule": ("trig", r"Inmediata: \(\int \csc^2 x\,dx = -\cot x\)"),
    "SecTanRule": ("trig", r"Inmediata: \(\int \sec x \tan x\,dx = \sec x\)"),
    "CscCotRule": ("trig", r"Inmediata: \(\int \csc x \cot x\,dx = -\csc x\)"),
    "SinhRule": ("hyperbolic", r"Inmediata: \(\int \sinh x\,dx = \cosh x\)"),
    "CoshRule": ("hyperbolic", r"Inmediata: \(\int \cosh x\,dx = \sinh x\)"),
    "ArctanRule": ("arctan", r"Inmediata: \(\int \frac{dx}{1 + x^2} = \arctan x\) (ajustando constantes)"),
    "ArcsinRule": ("arcsin", r"Inmediata: \(\int \frac{dx}{\sqrt{1 - x^2}} = \arcsin x\)"),
    "ArcsinhRule": ("arcsinh", r"Inmediata: \(\int \frac{dx}{\sqrt{1 + x^2}} = \operatorname{arcsinh} x\)"),
    "TrigSubstitutionRule": ("trig_substitution", "Sustitución trigonométrica"),
    "PiecewiseRule": ("piecewise", "Integral por tramos"),
}


def _atomic_note(rule: Rule) -> tuple[str, str]:
    name = type(rule).__name__
    if name == "ExpRule":
        if getattr(rule, "base", None) == sp.E:
            return "exponential", r"Inmediata: \(\int e^x\,dx = e^x\)"
        return "exponential", r"Inmediata: \(\int a^x\,dx = \frac{a^x}{\ln a}\)"
    if name in _ATOMIC_NOTES:
        return _ATOMIC_NOTES[name]
    if name.endswith("Rule") and name[:-4] in {"Erf", "FresnelS", "FresnelC", "Si", "Ci", "Ei", "Li", "Shi", "Chi"}:
        return "special_function", "Primitiva no elemental: se expresa con una función especial"
    return "table", "Integral inmediata (tabla)"


def _expand(b: _Builder, target: sp.Integral, rule: Rule) -> None:
    """Turn one node of the integral_steps tree into steps that solve `target`."""
    if not b.state.has(target):
        return
    while isinstance(rule, AlternativeRule):
        rule = rule.alternatives[0]
    w = target.variables[0]

    shortcut = _linear_power(target.function, w)
    if shortcut is not None:
        result, note = shortcut
        b.transform(target, result, "linear_power", note,
                    after_part=_render_result_part(b.state, target, result))
    elif isinstance(rule, DontKnowRule):
        _generic(b, target)
    elif isinstance(rule, ConstantTimesRule):
        inner = sp.Integral(rule.other, w)
        c = rule.constant
        note = (r"Sale el signo: \(\int -f = -\int f\)" if c == -1
                else r"Sale la constante: \(\int c\,f = c \int f\)")
        b.transform(target, c * inner, "constant_multiple", note)
        _expand(b, inner, rule.substep)
    elif isinstance(rule, AddRule):
        parts = [sp.Integral(s.integrand, w) for s in rule.substeps]
        b.transform(target, sp.Add(*parts), "sum", "La integral de una suma es la suma de las integrales")
        for part, sub in zip(parts, rule.substeps):
            _expand(b, part, sub)
    elif isinstance(rule, URule):
        _substitution(b, target, rule.u_func, rule.u_var, rule.substep.integrand, rule.substep)
    elif isinstance(rule, PartsRule):
        _parts(b, target, rule.u, rule.dv, rule.v_step.eval(), rule.second_step)
    elif isinstance(rule, CyclicPartsRule):
        _cyclic_parts(b, target, rule)
    elif isinstance(rule, RewriteRule):
        rewritten = sp.Integral(rule.rewritten, w)
        if isinstance(rule, CompleteSquareRule):
            rule_id, note = "complete_square", "Se completa el cuadrado"
        elif _is_partial_fraction_rewrite(target.function, rule.rewritten, w):
            rule_id, note = "partial_fractions", "Se descompone en fracciones simples"
        else:
            rule_id, note = "rewrite", "Se reescribe el integrando"
        b.transform(target, rewritten, rule_id, note)
        _expand(b, rewritten, rule.substep)
    else:
        rule_id, note = _atomic_note(rule)
        result = rule.eval()
        b.transform(target, result, rule_id, note,
                    after_part=_render_result_part(b.state, target, result))


def _is_partial_fraction_rewrite(f: sp.Expr, rewritten: sp.Expr, w: sp.Symbol) -> bool:
    # Structural comparison: any rewrite is mathematically equal to apart(f).
    return f.is_rational_function(w) and rewritten == sp.apart(f, w)


def _linear_power(f: sp.Expr, w: sp.Symbol) -> tuple[sp.Expr, str] | None:
    """c·(a·w + b)^n with (a, b) != (1, 0): integrated in one step, as in class."""
    c, rest = f.as_independent(w, as_Add=False)
    base, n = rest.as_base_exp()
    if n.has(w) or not base.is_polynomial(w) or sp.degree(base, w) != 1:
        return None
    a, b0 = sp.Poly(base, w).all_coeffs()
    if a == 1 and b0 == 0:
        return None
    if n == -1:
        return (c * sp.log(base) / a,
                r"Inmediata: \(\int \frac{dx}{a x + b} = \frac{1}{a} \ln(a x + b)\)")
    return (c * base ** (n + 1) / (a * (n + 1)),
            r"Inmediata: \(\int (a x + b)^n\,dx = \frac{(a x + b)^{n+1}}{a (n+1)}\)")


def _render_result_part(state: sp.Expr, target: sp.Expr, result: sp.Expr) -> str | None:
    # Color what this step produced, unless it is the whole expression.
    return None if state == target else colored(tex(result), "changed")


def _generic(b: _Builder, target: sp.Integral) -> None:
    w = target.variables[0]
    antiderivative = find_antiderivative(target.function, w)
    b.generic = True
    b.transform(target, antiderivative.expr, "generic",
                "SymPy resolvió esta integral con un algoritmo general (no hay pasos de clase)")


def _differential(coefficient: sp.Expr, dw: str) -> str:
    """LaTeX of coefficient·dw as written in class: dx, -dx, 2x\\,dx, (2x + 1)\\,dx."""
    if coefficient == 1:
        return f"d{dw}"
    if coefficient == -1:
        return f"-d{dw}"
    body = tex(coefficient)
    if isinstance(coefficient, sp.Add):
        body = f"\\left({body}\\right)"
    return f"{body}\\,d{dw}"


def _parts(b: _Builder, target: sp.Integral, u: sp.Expr, dv: sp.Expr, v: sp.Expr,
           second_step: Rule | None) -> sp.Integral | None:
    """∫u dv = u·v − ∫v du. Returns the remaining integral (or None if it is 0)."""
    w = target.variables[0]
    du = sp.diff(u, w)
    rest_integrand = v * du
    rest = sp.Integral(rest_integrand, w) if rest_integrand != 0 else None
    replacement = u * v - (rest if rest is not None else 0)

    dw = tex(w)
    before_part = integral_tex(f"{factor_tex(u, 'u')} \\cdot {factor_tex(dv, 'dv')}", w)
    after_part = f"{factor_tex(u, 'u')} \\cdot {factor_tex(v, 'v')}"
    if rest is not None:
        rest_tex = factor_tex(v, "v") if du == 1 else f"{factor_tex(v, 'v')} \\cdot {factor_tex(du, 'du')}"
        after_part += " - " + integral_tex(rest_tex, w)
    aux = {"u": tex(u), "du": _differential(du, dw), "dv": _differential(dv, dw), "v": tex(v)}
    note = (rf"Partes: \(u = {aux['u']} \Rightarrow du = {aux['du']}\); "
            rf"\(dv = {aux['dv']} \Rightarrow v = {aux['v']}\)")
    highlight = [Highlight(role, aux[role]) for role in ("u", "du", "dv", "v")]
    b.transform(target, replacement, "parts", note, before_part=before_part, after_part=after_part,
                aux=aux, highlight=highlight)
    if rest is not None and second_step is not None:
        _expand(b, rest, second_step)
    return rest


def _cyclic_parts(b: _Builder, target: sp.Integral, rule: CyclicPartsRule) -> None:
    """Parts until the original integral I shows up again, then solve for I."""
    w = target.variables[0]
    state_before = b.state
    current: sp.Integral | None = target
    for parts_rule in rule.parts_rules:
        if current is None:
            break
        current = _parts(b, current, parts_rule.u, parts_rule.dv, parts_rule.v_step.eval(), None)

    result = rule.eval()
    new_state = state_before.xreplace({target: result})
    status = _antiderivative_status(result, target.function, w)
    i_tex = tex(target) if state_before == target else "I"
    b.replace_state(
        new_state, "solve_for_integral",
        r"Reaparece la integral original \(I\): se pasa al otro miembro y se despeja \(I\)",
        before=f"{i_tex} = {tex(b.state)}",
        after=_render(new_state, result, colored(tex(result), "result") if state_before == target else None),
        status=status,
    )


def _substitution(b: _Builder, target: sp.Integral, g: sp.Expr, u: sp.Symbol, h: sp.Expr,
                  sub_rule: Rule | None) -> None:
    """∫f(x) dx -> ∫h(u) du with u = g(x); solve in u; go back to x."""
    w = target.variables[0]
    dg = sp.diff(g, w)
    status = _zero_status(h.subs(u, g) * dg - target.function, w)
    if status == "failed":
        raise IntegrationError(f"The substitution u = {sp.sstr(g)} does not turn the integrand into a function of u.")

    in_u = sp.Integral(h, u)
    dw = tex(w)
    aux = {"u": tex(g), "du": _differential(dg, dw)}
    b.transform(
        target, in_u, "substitution",
        rf"Sustitución: \(u = {aux['u']} \Rightarrow du = {aux['du']}\)",
        before_part=integral_tex(tex_marking(target.function, {g: "u"}), w),
        after_part=integral_tex(tex_marking(h, {u: "u"}), u),
        aux=aux, highlight=[Highlight("u", aux["u"]), Highlight("du", aux["du"])],
        status=status,
    )
    _expand(b, in_u, sub_rule if sub_rule is not None else integral_steps(h, u))
    if b.state.has(u):
        back = b.state.subs(u, g)
        b.replace_state(
            back, "back_substitution", rf"Se vuelve a \({dw}\) reemplazando \(u = {tex(g)}\)",
            before=tex_marking(b.state, {u: "u"}), after=tex_marking(back, {g: "u"}),
            status="symbolic",  # exact replacement; the final derivative check covers the rest
            aux={"u": tex(g)},
        )


# --- User-chosen methods ------------------------------------------------------------

def _user_parts(b: _Builder, target: sp.Integral, u: sp.Expr, dv: sp.Expr | None) -> None:
    x = target.variables[0]
    f = target.function
    if not u.has(x):
        raise IntegrationError(f"u must depend on {x}; got u = {sp.sstr(u)}.")
    if dv is None:
        dv = sp.powsimp(sp.cancel(f / u))
    elif _zero_status(u * dv - f, x) == "failed":
        raise IntegrationError(
            f"u·dv must equal the integrand: u·dv = {sp.sstr(u * dv)}, integrand = {sp.sstr(f)}."
        )
    try:
        v = find_antiderivative(dv, x).expr
    except IntegrationError:
        raise IntegrationError(
            f"With u = {sp.sstr(u)}, dv = {sp.sstr(dv)} d{x} has no antiderivative SymPy can find. Try another u."
        ) from None
    rest = _parts(b, target, u, dv, v, None)
    if rest is not None:
        _expand(b, rest, integral_steps(rest.function, x))


def _rewrite_in_u(f: sp.Expr, g: sp.Expr, dg: sp.Expr, u: sp.Symbol, x: sp.Symbol) -> sp.Expr:
    ratio = sp.cancel(f / dg)
    for candidate in (ratio.subs(g, u), sp.simplify(ratio).subs(g, u)):
        if not candidate.has(x):
            return candidate
    try:
        inverses = sp.solve(sp.Eq(u, g), x)
    except (NotImplementedError, ValueError):
        inverses = []
    for inverse in inverses:
        candidate = sp.simplify(ratio.subs(x, inverse))
        if not candidate.has(x) and _zero_status(candidate.subs(u, g) * dg - f, x) != "failed":
            return candidate
    leftover = ratio.subs(g, u)
    raise IntegrationError(
        f"The substitution u = {sp.sstr(g)} does not eliminate {x}: the integrand becomes "
        f"{sp.sstr(leftover)} du, which still has {x}. Try another u."
    )


def _user_substitution(b: _Builder, target: sp.Integral, g: sp.Expr) -> None:
    x = target.variables[0]
    if not g.has(x):
        raise IntegrationError(f"u must depend on {x}; got u = {sp.sstr(g)}.")
    dg = sp.diff(g, x)
    if dg == 0:
        raise IntegrationError(f"u = {sp.sstr(g)} has derivative 0; try another u.")
    name = "t" if any(s.name == "u" for s in target.free_symbols) else "u"
    u = sp.Dummy(name)
    h = _rewrite_in_u(target.function, g, dg, u, x)
    _substitution(b, target, g, u, h, None)


def _factor_power_tex(p: sp.Expr, m: int, alone: bool) -> str:
    base = tex(p)
    if isinstance(p, sp.Add) and (m > 1 or not alone):
        base = paren(base)
    return base if m == 1 else f"{base}^{{{m}}}"


def _user_partial_fractions(b: _Builder, target: sp.Integral) -> None:
    x = target.variables[0]
    f = target.function
    num, den = sp.fraction(sp.cancel(sp.together(f)))
    if not f.is_rational_function(x) or not den.has(x):
        raise IntegrationError(
            f"Partial fractions needs a rational function in {x} (polynomial / polynomial "
            f"with {x} in the denominator); got {sp.sstr(f)}."
        )

    work = target
    if sp.degree(num, x) >= sp.degree(den, x):
        q, r = sp.div(num, den, x)
        poly_part = sp.Integral(q, x)
        rest = sp.Integral(r / den, x) if r != 0 else None
        b.transform(
            target, poly_part + (rest if rest is not None else 0), "polynomial_division",
            r"El grado del numerador no es menor que el del denominador: se dividen los polinomios",
        )
        _expand(b, poly_part, integral_steps(q, x))
        if rest is None:
            return
        work, num = rest, r

    coeff, factors = sp.factor_list(den, x)
    names = iter(_CONSTANT_NAMES)
    unknowns: list[sp.Symbol] = []
    terms: list[sp.Expr] = []
    for p, m in factors:
        degree = sp.degree(p, x)
        if degree > 2:
            raise IntegrationError(
                f"The denominator has an irreducible factor of degree {degree} ({sp.sstr(p)}); "
                "partial fractions here handles linear and quadratic factors only."
            )
        for k in range(1, m + 1):
            if degree == 1:
                a = sp.Symbol(next(names))
                unknowns.append(a)
                terms.append(a / p**k)
            else:
                bb, cc = sp.Symbol(next(names)), sp.Symbol(next(names))
                unknowns += [bb, cc]
                terms.append((bb * x + cc) / p**k)

    numerator = num / coeff
    product = sp.Mul(*[p**m for p, m in factors])
    product_tex = r" ".join(_factor_power_tex(p, m, alone=len(factors) == 1) for p, m in factors)
    multiplied = [sp.cancel(t * product) for t in terms]
    equation = sp.expand(numerator - sp.Add(*multiplied))
    solutions = sp.solve(sp.Poly(equation, x).all_coeffs(), unknowns, dict=True)
    if not solutions:
        raise IntegrationError("Could not solve for the partial fraction constants.")
    solution = solutions[0]
    pieces = [t.subs(solution) for t in terms]
    status = _zero_status(sp.Add(*pieces) - work.function, x)

    marks = {a: "const" for a in unknowns}
    fraction_tex = rf"\frac{{{tex(numerator)}}}{{{product_tex}}}"
    b.side_step(
        rf"\frac{{{tex(num)}}}{{{tex(den)}}}", fraction_tex, "factor_denominator",
        "Se factoriza el denominador", _zero_status(numerator / product - work.function, x),
    )
    b.side_step(
        fraction_tex, tex_marking(sp.Add(*terms), marks), "partial_fractions_setup",
        "Planteo: una fracción por cada factor del denominador (y por cada potencia si se repite)",
        status,
    )
    values = {a: solution.get(a, sp.Integer(0)) for a in unknowns}
    b.side_step(
        f"{tex(numerator)} = {tex_marking(sp.Add(*multiplied), marks)}",
        r",\quad ".join(f"{colored(tex(a), 'const')} = {tex(val)}" for a, val in values.items()),
        "partial_fractions_constants",
        "Se multiplica por el denominador y se igualan coeficientes (o se evalúa en las raíces)",
        status, aux={tex(a): tex(val) for a, val in values.items()},
        highlight=[Highlight("const", tex(a)) for a in unknowns],
    )
    integrals = [sp.Integral(piece, x) for piece in pieces if piece != 0]
    b.transform(work, sp.Add(*integrals), "partial_fractions",
                "Se reemplaza la descomposición y se integra cada fracción por separado")
    for integral in integrals:
        _expand(b, integral, integral_steps(integral.function, x))


# --- Entry points ----------------------------------------------------------------------

def integrate_with_steps(
    integrand: sp.Expr,
    x: sp.Symbol,
    method: StepMethod = "auto",
    u: sp.Expr | None = None,
    dv: sp.Expr | None = None,
    constant: str | None = "C",
) -> StepByStep:
    """Solve ∫integrand dx step by step with the method the user chose.

    `constant`: name of the integration constant for the "+ C" step, or None to
    skip that step (definite integrals).
    """
    problem = sp.Integral(integrand, x)
    b = _Builder(problem)

    if method == "auto":
        try:
            _expand(b, problem, integral_steps(integrand, x))
            if b.state.has(sp.Integral):
                raise IntegrationError("Could not finish solving the integral step by step.")
        except IntegrationError:
            # No textbook steps that pass every check: solve it in one generic, checked step.
            b = _Builder(problem)
            _generic(b, problem)
    elif method == "parts":
        if u is None:
            raise IntegrationError("Integration by parts needs u (and optionally dv).")
        _user_parts(b, problem, u, dv)
    elif method == "substitution":
        if u is None:
            raise IntegrationError("Substitution needs u as a function of x, e.g. u = x**2.")
        _user_substitution(b, problem, u)
    elif method == "partial_fractions":
        _user_partial_fractions(b, problem)
    else:
        raise IntegrationError(f"Unknown method {method!r}.")

    if b.state.has(sp.Integral):
        raise IntegrationError("Could not finish solving the integral step by step.")
    antiderivative = b.state

    if constant is not None:
        b.side_step(tex(antiderivative), f"{tex(antiderivative)} + {colored(constant, 'result')}",
                    "constant_of_integration", "Se suma la constante de integración", "symbolic")

    check = verify_antiderivative(integrand, antiderivative, x)
    if check.status == "incorrect":
        raise IntegrationError("The result did not pass the derivative check, so no steps are shown.")
    dx = tex(x)
    b.side_step(
        rf"\frac{{d}}{{d{dx}}}\left({tex(antiderivative)}\right)",
        rf"{colored(tex(integrand), 'result')} \;\checkmark",
        "derivative_check",
        "Verificación: la derivada de la primitiva es el integrando",
        "symbolic" if check.status == "verified" else "numeric",
    )

    verified = check.status == "verified" and not b.numeric_only
    return StepByStep(b.steps, antiderivative, method, b.generic, "verified" if verified else "inconclusive")


def definite_step(antiderivative: sp.Expr, x: sp.Symbol, lower: sp.Expr, upper: sp.Expr,
                  result: DefiniteIntegral) -> Step:
    """Last step of a definite integral: Barrow's rule, or limits if it is improper."""
    bracket = rf"\Big[\, {tex(antiderivative)} \,\Big]_{{{tex(lower)}}}^{{{tex(upper)}}}"
    if result.status == "diverges":
        points = ", ".join(sp.sstr(p) for p in result.discontinuities) or "el infinito"
        return Step(bracket, r"\text{diverge}", "improper_diverges",
                    f"Integral impropia: algún límite lateral no es finito (en {points}), así que diverge",
                    verified=result.verification.status == "verified")
    assert result.value is not None
    if result.improper:
        note = "Integral impropia: se parte el intervalo y se toman límites laterales de la primitiva"
        rule = "improper_limits"
    else:
        note = r"Regla de Barrow: \(F(b) - F(a)\)"
        rule = "barrow"
    return Step(bracket, colored(tex(result.value), "result"), rule, note,
                verified=result.verification.status == "verified")
