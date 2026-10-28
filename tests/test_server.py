"""End to end through the MCP protocol (in-memory client) and the sandbox."""

import pytest
from mcp.client import Client

from step_by_step_math.server import server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def call(tool: str, args: dict):
    async with Client(server) as client:
        return await client.call_tool(tool, args)


async def test_lists_three_tools():
    async with Client(server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert names == {"differentiate", "integrate", "verify_antiderivative"}


async def test_differentiate():
    r = await call("differentiate", {"expression": "x**2*sen(x)"})
    assert not r.is_error
    assert r.structured_content["result"] == "x**2*cos(x) + 2*x*sin(x)"


async def test_integrate_indefinite():
    r = await call("integrate", {"expression": "x*exp(x)"})
    assert r.structured_content == {
        "kind": "indefinite",
        "result": "x*exp(x) - exp(x) + C",
        "latex": "x e^{x} - e^{x} + C",
        "method": "manualintegrate",
        "verification": "verified",
    }


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
