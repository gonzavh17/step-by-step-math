"""Step-by-step integration: one test per method, error cases, and LaTeX that KaTeX accepts."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import sympy as sp

from step_by_step_math.engines.calculus.integrals import IntegrationError
from step_by_step_math.engines.calculus.integration_steps import integrate_with_steps

x = sp.Symbol("x")

KATEX_VERSION = "0.18.11"  # same as the whiteboard


def rules(solved) -> list[str]:
    return [s.rule for s in solved.steps]


def check_result(solved, f) -> None:
    assert sp.simplify(sp.diff(solved.antiderivative, x) - f) == 0
    assert solved.verification == "verified"
    assert all(s.verified for s in solved.steps)
    assert rules(solved)[-1] == "derivative_check"


def test_parts_with_user_u():
    f = x * sp.exp(x)
    solved = integrate_with_steps(f, x, "parts", u=x)
    check_result(solved, f)
    assert rules(solved) == ["parts", "exponential", "constant_of_integration", "derivative_check"]
    parts = solved.steps[0]
    assert parts.aux["u"] == "x"
    assert parts.aux["v"] == "e^{x}"
    assert "dv" in parts.aux and "du" in parts.aux


def test_parts_with_u_and_dv():
    f = x * sp.cos(x)
    solved = integrate_with_steps(f, x, "parts", u=x, dv=sp.cos(x))
    check_result(solved, f)
    assert rules(solved)[0] == "parts"


def test_parts_respects_the_users_u():
    # u = e^x is the "wrong" choice in class, but it is the user's: the engine follows it.
    f = x * sp.exp(x)
    solved = integrate_with_steps(f, x, "parts", u=sp.exp(x))
    check_result(solved, f)
    assert solved.steps[0].aux["u"] == "e^{x}"


def test_parts_dv_mismatch():
    with pytest.raises(IntegrationError, match="u"):
        integrate_with_steps(x * sp.exp(x), x, "parts", u=x, dv=sp.sin(x))


def test_parts_needs_u():
    with pytest.raises(IntegrationError, match="needs u"):
        integrate_with_steps(x * sp.exp(x), x, "parts")


def test_substitution():
    f = 2 * x * sp.cos(x**2)
    solved = integrate_with_steps(f, x, "substitution", u=x**2)
    check_result(solved, f)
    assert rules(solved) == ["substitution", "trig", "back_substitution", "constant_of_integration", "derivative_check"]


def test_substitution_leaves_x_free():
    with pytest.raises(IntegrationError, match="Try another u"):
        integrate_with_steps(x * sp.cos(x**2) * sp.exp(x), x, "substitution", u=x**2)


def test_substitution_constant_u():
    with pytest.raises(IntegrationError, match="must depend on x"):
        integrate_with_steps(sp.cos(x), x, "substitution", u=sp.Integer(3))


def test_partial_fractions_shows_setup():
    f = (x + 1) / (x**2 - 5 * x + 6)
    solved = integrate_with_steps(f, x, "partial_fractions")
    check_result(solved, f)
    r = rules(solved)
    assert r[:4] == ["factor_denominator", "partial_fractions_setup", "partial_fractions_constants", "partial_fractions"]
    setup = solved.steps[1]
    assert "A" in setup.after and "B" in setup.after


def test_partial_fractions_with_quadratic_factor():
    f = 1 / (x**3 + x)
    solved = integrate_with_steps(f, x, "partial_fractions")
    check_result(solved, f)


def test_partial_fractions_not_rational():
    with pytest.raises(IntegrationError):
        integrate_with_steps(sp.sin(x) / (x + 1), x, "partial_fractions")


@pytest.mark.parametrize(
    "f",
    [
        x * sp.exp(x),
        sp.exp(x) * sp.sin(x),  # cyclic parts
        3 * x**2 + 2 * x + 1,
        1 / (2 * x + 3) ** 2,
        sp.log(x),
        x**2 * sp.sin(x),
        1 / (x**2 + 4 * x + 5),  # complete the square
        sp.cos(x) ** 2,
    ],
)
def test_auto_verifies(f):
    check_result(integrate_with_steps(f, x), f)


def test_auto_generic_fallback_is_marked():
    f = 1 / (2 + sp.cos(x))
    solved = integrate_with_steps(f, x)
    # The antiderivative has floor() terms (to stay continuous); the engine's own check handles them.
    assert solved.verification == "verified"
    assert solved.generic_fallback
    assert "generic" in rules(solved)


def test_one_step_has_one_rule():
    # Each step changes the expression (no repeated or empty steps).
    solved = integrate_with_steps(x**2 * sp.exp(x), x)
    for s in solved.steps:
        if s.rule not in ("derivative_check",):
            assert s.before != s.after, s.rule


# --- LaTeX checked with the real KaTeX ---------------------------------------------------

CASES = [
    (x * sp.exp(x), "parts", x, None),
    (x * sp.cos(x), "parts", x, sp.cos(x)),
    (2 * x * sp.cos(x**2), "substitution", x**2, None),
    (sp.sin(x) ** 3 * sp.cos(x), "substitution", sp.sin(x), None),
    ((x + 1) / (x**2 - 5 * x + 6), "partial_fractions", None, None),
    ((x**3 + 1) / (x**2 - 1), "partial_fractions", None, None),
    (1 / (x**3 + x), "partial_fractions", None, None),
    (sp.exp(x) * sp.sin(x), "auto", None, None),
    (sp.log(x), "auto", None, None),
    (1 / (x**2 + 4 * x + 5), "auto", None, None),
    (1 / (2 + sp.cos(x)), "auto", None, None),
]


def _katex_dir() -> Path | None:
    """KaTeX installed with npm into a cache dir (reused between runs). None when unavailable."""
    if not shutil.which("node") or not shutil.which("npm"):
        return None
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "step-by-step-math" / f"katex-{KATEX_VERSION}"
    module = root / "node_modules" / "katex"
    if not module.exists():
        root.mkdir(parents=True, exist_ok=True)
        done = subprocess.run(
            ["npm", "install", "--silent", "--no-audit", "--no-fund", "--prefix", str(root), f"katex@{KATEX_VERSION}"],
            capture_output=True,
            timeout=180,
        )
        if done.returncode != 0 or not module.exists():
            return None
    return module


# Renders every formula the way the whiteboard does (throwOnError, same macros-free setup)
# and prints the ones that fail.
_NODE_SCRIPT = r"""
const katex = require(process.argv[1]);
const items = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const bad = [];
for (const [where, tex, display] of items) {
  try { katex.renderToString(tex, {throwOnError: true, displayMode: display, strict: 'ignore'}); }
  catch (e) { bad.push([where, tex, String(e.message)]); }
}
process.stdout.write(JSON.stringify(bad));
"""


def _inline_math(note: str) -> list[str]:
    parts = []
    rest = note
    while r"\(" in rest:
        start = rest.index(r"\(") + 2
        end = rest.index(r"\)", start)
        parts.append(rest[start:end])
        rest = rest[end + 2 :]
    return parts


def test_all_step_latex_renders_in_katex():
    katex = _katex_dir()
    if katex is None:
        pytest.skip("node/npm or KaTeX not available")
    items = []
    for f, method, u, dv in CASES:
        solved = integrate_with_steps(f, x, method, u, dv)
        for i, s in enumerate(solved.steps):
            where = f"{f} [{method}] step {i} ({s.rule})"
            items.append([where + " before", s.before, True])
            items.append([where + " after", s.after, True])
            for key, value in s.aux.items():
                items.append([f"{where} aux {key}", value, False])
            for h in s.highlight:
                items.append([f"{where} highlight", h.latex, False])
            for m in _inline_math(s.note):
                items.append([where + " note", m, False])
    out = subprocess.run(
        ["node", "-e", _NODE_SCRIPT, str(katex)],
        input=json.dumps(items),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == []
