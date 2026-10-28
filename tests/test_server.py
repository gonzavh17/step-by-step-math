"""End to end through the MCP protocol (in-memory client) and the sandbox."""

import pytest
from mcp.client import Client

from step_by_step_math import server as server_module
from step_by_step_math.server import BOARD_URI, server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def call(tool: str, args: dict):
    async with Client(server) as client:
        return await client.call_tool(tool, args)


async def test_lists_tools():
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {"differentiate", "integrate", "verify_antiderivative", "get_board"}
    # Only integrate opens the whiteboard; get_board is for the app, not the model.
    assert tools["integrate"].meta["ui"]["resourceUri"] == BOARD_URI
    assert tools["get_board"].meta["ui"] == {"visibility": ["app"]}
    assert tools["differentiate"].meta is None


async def test_board_resource():
    async with Client(server) as client:
        resources = (await client.list_resources()).resources
        assert [r.uri for r in resources] == [BOARD_URI]
        assert resources[0].meta["ui"]["csp"] == {"resourceDomains": ["https://cdnjs.cloudflare.com"]}
        content = (await client.read_resource(BOARD_URI)).contents[0]
    assert content.mime_type == "text/html;profile=mcp-app"
    assert "board-data" in content.text


async def test_differentiate():
    r = await call("differentiate", {"expression": "x**2*sen(x)"})
    assert not r.is_error
    assert r.structured_content["result"] == "x**2*cos(x) + 2*x*sin(x)"


async def test_integrate_indefinite():
    r = await call("integrate", {"expression": "x*exp(x)"})
    out = dict(r.structured_content)
    board_id = out.pop("board_id")
    assert out == {
        "kind": "indefinite",
        "result": "x*exp(x) - exp(x) + C",
        "latex": "x e^{x} - e^{x} + C",
        "method": "auto",
        "verification": "verified",
        "steps": 4,
    }
    assert len(board_id) == 32


async def test_integrate_parts_board_goes_to_the_app_only():
    r = await call("integrate", {"expression": "x*exp(x)", "method": "parts", "u": "x"})
    assert not r.is_error
    out = r.structured_content
    assert out["method"] == "parts"
    assert "board" not in out and "\\textcolor" not in r.content[0].text  # no steps in the model's context
    b = await call("get_board", {"board_id": out["board_id"]})
    assert not b.is_error
    board = b.structured_content
    assert board["id"] == out["board_id"]
    assert [s["rule"] for s in board["steps"]] == ["parts", "exponential", "constant_of_integration", "derivative_check"]


async def test_get_board_unknown():
    r = await call("get_board", {"board_id": "missing"})
    assert r.is_error
    assert "expired" in r.content[0].text


async def test_get_board_skips_the_sandbox(monkeypatch):
    r = await call("integrate", {"expression": "x"})

    def fail(*args):
        raise AssertionError("get_board must not run in the sandbox")

    monkeypatch.setattr(server_module, "run_isolated", fail)
    b = await call("get_board", {"board_id": r.structured_content["board_id"]})
    assert not b.is_error


async def test_integrate_invalid_substitution_is_actionable():
    r = await call("integrate", {"expression": "x*cos(x**2)*exp(x)", "method": "substitution", "u": "x**2"})
    assert r.is_error
    assert "Try another u" in r.content[0].text


async def test_integrate_u_without_method():
    r = await call("integrate", {"expression": "x*exp(x)", "u": "x"})
    assert r.is_error
    assert "only applies" in r.content[0].text


async def test_integrate_board_path_over_stdio(monkeypatch, tmp_path):
    monkeypatch.setattr(server_module, "_board_dir", tmp_path)
    r = await call("integrate", {"expression": "x*exp(x)", "method": "parts", "u": "x"})
    path = r.structured_content["board_path"]
    assert path.startswith(str(tmp_path))
    assert "parts" in open(path, encoding="utf-8").read()


async def test_integrate_board_url_over_http(monkeypatch):
    monkeypatch.setattr(server_module, "_board_base_url", "https://example.test")
    r = await call("integrate", {"expression": "x"})
    out = r.structured_content
    assert out["board_url"] == f"https://example.test/board/{out['board_id']}"


async def test_integrate_definite_diverges():
    r = await call("integrate", {"expression": "1/x**2", "lower": "-1", "upper": "1"})
    out = r.structured_content
    assert not r.is_error
    assert out["status"] == "diverges"
    assert out["result"] is None
    assert out["discontinuities"] == ["0"]
    assert "diverges" in out["explanation"]


async def test_integrate_one_limit_only():
    r = await call("integrate", {"expression": "x", "lower": "0"})
    assert r.is_error
    assert "both limits" in r.content[0].text


async def test_integrate_bound_with_variable():
    r = await call("integrate", {"expression": "x", "lower": "0", "upper": "x"})
    assert r.is_error
    assert "must be a constant" in r.content[0].text


async def test_verify_inconclusive_has_note():
    r = await call("verify_antiderivative", {"integrand": "1/cos(x)", "antiderivative": "ln(tg(x/2 + pi/4))"})
    out = r.structured_content
    assert out["status"] == "inconclusive"
    assert "could not prove" in out["note"]


async def test_verify_incorrect():
    r = await call("verify_antiderivative", {"integrand": "x", "antiderivative": "x**2"})
    assert r.structured_content["status"] == "incorrect"
    assert r.structured_content["difference"] == "x"


async def test_timeout_is_tool_error(monkeypatch):
    monkeypatch.setenv("STEP_BY_STEP_MATH_TIMEOUT", "1")
    r = await call("integrate", {"expression": "(x**7 + 3)/(x**13 + x + 1)"})
    assert r.is_error
    assert "more than 1 s" in r.content[0].text


async def test_integrate_numeric_limits():
    r = await call("integrate", {"expression": "x**2", "lower": 0, "upper": 1.5})
    assert not r.is_error
    assert r.structured_content["result"] == "1.12500000000000"
