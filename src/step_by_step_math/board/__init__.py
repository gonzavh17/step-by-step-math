"""Whiteboard renderer: one self-contained HTML (KaTeX from cdnjs) for every engine.

The same template serves two cases:
- MCP App (`app_html`): no data inside; the page asks the host for the tool
  result and then calls the app-only `get_board` tool.
- Standalone page (`page_html`): the board JSON is embedded in the page.

No math here: it only draws the LaTeX in the steps.
"""

import json
from functools import cache
from importlib.resources import files
from typing import Any

_PLACEHOLDER = "__BOARD_DATA__"

KATEX_ORIGIN = "https://cdnjs.cloudflare.com"

# For the standalone page (/board/<id>): only our inline code and KaTeX from cdnjs.
PAGE_CSP = (
    "default-src 'none'; "
    f"script-src 'unsafe-inline' {KATEX_ORIGIN}; "
    f"style-src 'unsafe-inline' {KATEX_ORIGIN}; "
    f"font-src {KATEX_ORIGIN}; "
    "img-src data:; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


@cache
def _template() -> str:
    return files(__package__).joinpath("board.html").read_text(encoding="utf-8")


def app_html() -> str:
    """HTML for the MCP App resource (data arrives through the host)."""
    return _template().replace(_PLACEHOLDER, "null")


def page_html(board: dict[str, Any]) -> str:
    """Standalone HTML page with the board embedded."""
    data = json.dumps(board, ensure_ascii=False)
    # Safe inside <script type="application/json">: no "</script>" or "<!--" can appear.
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return _template().replace(_PLACEHOLDER, data)
