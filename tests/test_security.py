"""HTTP-level hardening tests: Origin/Host checks, rate limit, body cap, headers, logs."""
import importlib
import json
import logging

import pytest
from starlette.testclient import TestClient

MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
               "MCP-Protocol-Version": "2025-11-25"}


def payload(resp):
    r = resp.json()["result"]
    return r.get("structuredContent") or json.loads(r["content"][0]["text"])


def call(name, args=None, rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}


@pytest.fixture
def make_client(monkeypatch, tmp_path):
    clients = []

    def _make(**env):
        monkeypatch.setenv("VOICESTACK_DB", str(tmp_path / f"t{len(clients)}.db"))
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        import voicestack.server as srv
        srv = importlib.reload(srv)
        c = TestClient(srv.app, base_url="http://localhost:8000")
        c.__enter__()
        clients.append(c)
        return c, srv
    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def test_security_headers_and_request_id(make_client):
    c, _ = make_client()
    r = c.get("/api/health", headers={"X-Request-ID": "abc-123"})
    assert r.status_code == 200 and r.json()["version"] == 4
    assert r.headers["x-request-id"] == "abc-123"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    bad = c.get("/api/health", headers={"X-Request-ID": "bad id with spaces\t"})
    assert bad.headers["x-request-id"] != "bad id with spaces\t" and len(bad.headers["x-request-id"]) == 16


def test_cross_origin_and_foreign_host_refused(make_client):
    c, _ = make_client()
    r = c.post("/api/parse", json={"text": "kal 5 baje haircut"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"] == "forbidden_origin"
    r = c.post("/mcp", json=call("find_businesses"), headers={**MCP_HEADERS, "Origin": "https://evil.example"})
    assert r.status_code == 403
    ok = c.post("/api/parse", json={"text": "kal 5 baje haircut"}, headers={"Origin": "http://localhost:8000"})
    assert ok.status_code == 200
    r = c.get("/api/health", headers={"Host": "evil.example"})
    assert r.status_code == 403 and r.json()["error"] == "forbidden_host"


def test_rate_limit(make_client):
    c, _ = make_client(VOICESTACK_RATE_PER_MIN="5")
    codes = [c.get("/api/health").status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]
    assert "retry-after" in c.get("/api/health").headers


def test_body_cap(make_client):
    c, _ = make_client()
    big = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "find_businesses", "arguments": {"query": "x" * 1_200_000}}}
    assert c.post("/mcp", json=big, headers=MCP_HEADERS).status_code == 413


def test_parse_input_limits(make_client):
    c, _ = make_client()
    assert c.post("/api/parse", content=b"not json", headers={"Content-Type": "application/json"}).status_code == 400
    assert c.post("/api/parse", json={"text": "x" * 100000, "service_names": ["a"] * 500}).status_code == 200
    assert c.get("/api/audit?business_id=x&limit=abc").status_code == 400


def test_seed_can_be_disabled_and_ready_probe(make_client):
    c, _ = make_client(VOICESTACK_ENABLE_SEED="0")
    assert c.post("/api/seed").status_code == 404
    assert c.get("/api/ready").json() == {"ok": True}


def test_logs_are_structured_and_never_contain_request_data(make_client, caplog):
    c, _ = make_client()
    with caplog.at_level(logging.INFO, logger="voicestack.access"):
        c.post("/mcp", json=call("onboard_business", {"name": "Secret Shop", "description": "haircut 300"}),
               headers={**MCP_HEADERS, "X-Request-ID": "rid-42"})
    lines = [json.loads(r.message) for r in caplog.records if r.name == "voicestack.access"]
    assert lines and lines[-1]["rid"] == "rid-42" and lines[-1]["tools"] == ["onboard_business"]
    assert lines[-1]["status"] == 200 and lines[-1]["ms"] >= 0
    assert "Secret Shop" not in caplog.text and "haircut 300" not in caplog.text


def test_public_tools_and_routes_work_without_credentials(make_client):
    c, _ = make_client()
    r = c.post("/mcp", json=call("onboard_business", {"name": "Test Shop", "description": "haircut 300, open 10-8"}), headers=MCP_HEADERS)
    assert r.status_code == 200 and payload(r)["status"] == "draft"
    assert c.get("/api/day?business_id=x&date=2026-10-26").status_code == 200
    assert c.get("/").status_code == 200


def test_batch_requests_are_logged_per_tool(make_client, caplog):
    c, _ = make_client()
    with caplog.at_level(logging.INFO, logger="voicestack.access"):
        c.post("/mcp", json=[call("find_businesses", {}, 1), call("check_waitlist", {"waitlist_id": "x"}, 2)], headers=MCP_HEADERS)
    lines = [json.loads(r.message) for r in caplog.records if r.name == "voicestack.access"]
    assert lines[-1]["tools"] == ["find_businesses", "check_waitlist"]


def test_default_settings():
    from voicestack.security import Settings
    s = Settings.from_env({})
    assert s.rate_per_min == 600 and s.enable_seed and not s.trust_proxy
    assert "localhost:*" in s.allowed_hosts
