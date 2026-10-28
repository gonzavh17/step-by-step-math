"""Board store and the whiteboard HTML."""

import json
import re

import pytest

from step_by_step_math.board import app_html, page_html
from step_by_step_math.boards import BoardStore
from step_by_step_math.tasks import integrate_task


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_ids_are_random_and_long():
    store = BoardStore()
    ids = {store.put({"n": i}) for i in range(50)}
    assert len(ids) == 50
    for board_id in ids:
        assert re.fullmatch(r"[A-Za-z0-9_-]{32}", board_id)  # 24 random bytes = 192 bits


def test_get_returns_board_with_id():
    store = BoardStore()
    board_id = store.put({"steps": []})
    assert store.get(board_id) == {"steps": [], "id": board_id}
    assert store.get("nope") is None


def test_boards_expire():
    clock = FakeClock()
    store = BoardStore(ttl_seconds=3600, clock=clock)
    board_id = store.put({})
    clock.now = 3599
    assert store.get(board_id) is not None
    clock.now = 3601
    assert store.get(board_id) is None


def test_oldest_board_is_evicted_at_the_limit():
    store = BoardStore(max_boards=3)
    first, *rest = [store.put({"n": i}) for i in range(4)]
    assert store.get(first) is None
    assert all(store.get(b) is not None for b in rest)
    assert len(store) == 3


@pytest.fixture(scope="module")
def parts_board():
    out = integrate_task("x*exp(x)", "x", None, None, "parts", "x", None)
    return {**out["board"], "id": "test-id"}


def _embedded_json(html: str):
    m = re.search(r'<script id="board-data" type="application/json">(.*?)</script>', html, re.S)
    assert m
    return json.loads(m.group(1))


def test_page_embeds_every_step(parts_board):
    html = page_html(parts_board)
    data = _embedded_json(html)
    assert data == parts_board
    assert [s["rule"] for s in data["steps"]] == ["parts", "exponential", "constant_of_integration", "derivative_check"]
    assert data["steps"][0]["aux"]["u"] == "x"
    assert data["result"]


def test_page_escapes_html_in_data():
    html = page_html({"problem": "</script><script>alert(1)</script>", "steps": []})
    assert "<script>alert(1)" not in html
    assert _embedded_json(html)["problem"] == "</script><script>alert(1)</script>"


def test_app_html_has_no_data_and_pins_katex():
    html = app_html()
    assert _embedded_json(html) is None
    assert "__BOARD_DATA__" not in html
    for asset in ("katex.min.js", "katex.min.css", "auto-render.min.js"):
        assert re.search(rf'cdnjs\.cloudflare\.com/ajax/libs/KaTeX/0\.18\.11/[\w/.-]*{re.escape(asset)}"[^>]*integrity="sha512-', html)
