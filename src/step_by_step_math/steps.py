"""Step contract shared by every engine, plus LaTeX helpers for highlighting.

Engines return `list[Step]`. The renderer only draws what is here: it never
parses or computes math. Highlighted subexpressions are already wrapped in
`\\textcolor{<role color>}{...}` inside `before` / `after`, and the palette
travels with the board so the legend uses the same colors.
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

import sympy as sp

# One fixed color per role, readable on a dark chalkboard.
PALETTE: dict[str, str] = {
    "u": "#7dd3fc",  # sky
    "du": "#a5b4fc",  # indigo
    "dv": "#fcd34d",  # amber
    "v": "#fdba74",  # orange
    "const": "#c4b5fd",  # violet (A, B, C in partial fractions)
    "result": "#86efac",  # green
    "changed": "#f9a8d4",  # pink (anything else that changed)
}


@dataclass(frozen=True)
class Highlight:
    role: str  # key of PALETTE
    latex: str  # the subexpression, plain LaTeX


@dataclass(frozen=True)
class Step:
    before: str  # LaTeX before the step (highlighted parts already colored)
    after: str  # LaTeX after the step
    rule: str  # rule id: "parts", "substitution", "power", "back_substitution", ...
    note: str  # one line for the margin; inline math between \( and \)
    highlight: list[Highlight] = field(default_factory=list)
    aux: dict[str, str] = field(default_factory=dict)  # rule data as LaTeX: {"u": "x", "du": "dx"}
    verified: bool = True  # False only when the step was checked numerically, not symbolically

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def tex(expr: sp.Basic) -> str:
    return sp.latex(expr, ln_notation=True)


def colored(latex: str, role: str) -> str:
    return rf"\textcolor{{{PALETTE[role]}}}{{{latex}}}"


def needs_parens(expr: sp.Basic) -> bool:
    """True if `expr` must be parenthesized when it is a factor of a product."""
    if isinstance(expr, sp.Add):
        return True
    return isinstance(expr, sp.Mul) and expr.could_extract_minus_sign()


def paren(latex: str) -> str:
    return rf"\left({latex}\right)"


def factor_tex(expr: sp.Basic, role: str | None = None) -> str:
    """LaTeX of `expr` as a factor in a product, optionally colored."""
    body = tex(expr)
    if role is not None:
        body = colored(body, role)
    return paren(body) if needs_parens(expr) else body


def needs_parens_at(tree: sp.Basic, ph: sp.Symbol, sub: sp.Basic) -> bool:
    """Whether `sub`, printed where placeholder `ph` sits in `tree`, needs parentheses.

    Only as a factor of a product or as the base of a power; not as a function
    argument, a term of a sum, a fraction's denominator (x^-1) or under a root.
    """
    if not needs_parens(sub):
        return False
    for node in sp.preorder_traversal(tree):
        if ph not in node.args:
            continue
        if isinstance(node, sp.Mul):
            return True
        if isinstance(node, sp.Pow) and node.base == ph:
            return node.exp not in (sp.Integer(-1), sp.S.Half, -sp.S.Half)
    return False


def tex_marking(expr: sp.Basic, marks: Mapping[sp.Basic, str]) -> str:
    """LaTeX of `expr` with each subexpression in `marks` colored by its role.

    Works by swapping each marked subexpression for a placeholder symbol,
    printing, and putting the colored LaTeX back. Only exact subtrees match.
    """
    placeholders: dict[sp.Symbol, tuple[sp.Basic, str]] = {}
    replaced = expr
    for i, (sub, role) in enumerate(marks.items()):
        ph = sp.Symbol(f"ZZPH{chr(65 + i)}ZZ")
        new = replaced.xreplace({sub: ph})
        if new != replaced:
            placeholders[ph] = (sub, role)
            replaced = new
    out = tex(replaced)
    for ph, (sub, role) in placeholders.items():
        piece = colored(tex(sub), role)
        if needs_parens_at(replaced, ph, sub):
            piece = paren(piece)
        out = out.replace(tex(ph), piece)
    return out


def tex_with_part(expr: sp.Basic, target: sp.Basic, part: str) -> str | None:
    """LaTeX of `expr` printing the single occurrence of `target` as `part`.

    None if `target` is not there exactly once (then coloring it would be ambiguous).
    """
    if expr == target:
        return part
    ph = sp.Symbol("ZZPARTZZ")
    replaced = expr.xreplace({target: ph})
    if replaced.count(ph) != 1:
        return None
    if needs_parens_at(replaced, ph, target):
        part = paren(part)
    return tex(replaced).replace(tex(ph), part)


def integral_tex(integrand_tex: str, variable: sp.Symbol) -> str:
    return rf"\int {integrand_tex} \, d{tex(variable)}"
