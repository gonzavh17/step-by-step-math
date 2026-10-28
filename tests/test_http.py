import threading
import time

import pytest
from starlette.testclient import TestClient

from step_by_step_math import sandbox, server

TOKEN = "t" * 40

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture
def client():
    with TestClient(server.http_app(TOKEN)) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_mcp_with_token(client):
    r = client.post(f"/mcp/{TOKEN}", json=INITIALIZE, headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["result"]["serverInfo"]["name"] == "step-by-step-math"


@pytest.mark.parametrize("path", ["/mcp", "/mcp/", "/mcp/wrong-token", f"/mcp/{TOKEN}x", "/"])
def test_mcp_without_valid_token_is_404(client, path):
    assert client.post(path, json=INITIALIZE, headers=HEADERS).status_code == 404


@pytest.mark.parametrize("value", ["", "short", "a" * 31, "has space" + "a" * 30, "a/b" + "a" * 30])
def test_path_token_rejected(monkeypatch, value):
    monkeypatch.setenv("STEP_BY_STEP_MATH_PATH_TOKEN", value)
    with pytest.raises(SystemExit, match="STEP_BY_STEP_MATH_PATH_TOKEN"):
        server.path_token()


def test_path_token_accepted(monkeypatch):
    monkeypatch.setenv("STEP_BY_STEP_MATH_PATH_TOKEN", TOKEN)
    assert server.path_token() == TOKEN


def test_unknown_transport(monkeypatch):
    monkeypatch.setenv("STEP_BY_STEP_MATH_TRANSPORT", "sse")
    with pytest.raises(SystemExit, match="stdio' or 'http"):
        server.main()


def test_busy_when_all_slots_taken(monkeypatch):
    monkeypatch.setattr(sandbox, "_slots", threading.BoundedSemaphore(1))
    worker = threading.Thread(target=sandbox.run_isolated, args=(time.sleep, 1.5), kwargs={"timeout": 5})
    worker.start()
    time.sleep(0.3)  # let the worker take the only slot
    try:
        with pytest.raises(sandbox.ComputationBusy, match="busy"):
            sandbox.run_isolated(sum, [1], timeout=0.3)
    finally:
        worker.join()
    assert sandbox.run_isolated(sum, [1, 2]) == 3  # slot released
