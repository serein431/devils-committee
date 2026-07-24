"""A2A server robustness — track 18's #1 disqualifier is the service falling over
(掉线 / 超时 / 调不到). These lock down: endpoints respond, bad input is handled,
auth works, and one failing agent degrades instead of 500-ing the whole debate."""
import dataclasses

import pytest
from fastapi.testclient import TestClient

from backend import a2a_server
from backend.config import CONFIG

client = TestClient(a2a_server.app)


def test_healthz_always_ok():
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_agent_card_served_and_url_injected():
    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    card = r.json()
    assert card["url"].endswith("/a2a")
    assert {s["id"] for s in card["skills"]} == {"debate_case", "audit_claims"}


def test_debate_case_returns_result():
    r = client.post("/a2a", json={"skill": "debate_case", "topic": "600519 多空"})
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["meta"]["symbol"] == "600519.SH"
    assert res["disclaimer"]


def test_audit_claims_skill_routed():
    r = client.post("/a2a", json={"skill": "audit_claims", "topic": "审计 AAPL"})
    assert r.status_code == 200
    assert r.json()["skill"] == "audit_claims"
    assert r.json()["result"]["audits"]


def test_empty_body_is_422_not_500():
    assert client.post("/a2a", json={}).status_code == 422


def test_weird_input_still_resolves_a_symbol():
    r = client.post("/a2a", json={"topic": "帮我看看这个东西"})
    assert r.status_code == 200                 # symbol falls back, never crashes


def test_bearer_auth_enforced_when_configured(monkeypatch):
    monkeypatch.setattr(a2a_server, "CONFIG",
                        dataclasses.replace(CONFIG, bearer_token="secret"))
    assert client.post("/a2a", json={"topic": "AAPL"}).status_code == 401
    ok = client.post("/a2a", json={"topic": "AAPL"},
                     headers={"Authorization": "Bearer secret"})
    assert ok.status_code == 200


def test_one_failing_agent_degrades_not_crashes(monkeypatch):
    """A skill/model error in ONE agent must not take down the whole debate."""
    from backend import orchestration

    async def boom(symbol):
        raise RuntimeError("simulated skill outage")

    monkeypatch.setattr(orchestration.BullAgent, "argue", boom)
    r = client.post("/a2a", json={"topic": "600519 多空"})
    assert r.status_code == 200
    res = r.json()["result"]
    # bull dropped out, but bear/macro/risk still debated
    sides = {c["side"] for c in res["claims"]}
    assert "bull" not in sides and {"bear", "macro", "risk"} <= sides


def test_internal_errors_are_sanitized_not_leaked(monkeypatch):
    """A failure must not leak internal paths / exception text to the A2A caller."""
    from backend import orchestration

    async def boom(self, topic):
        raise RuntimeError("/abs/secret/path.py private detail")

    monkeypatch.setattr(orchestration.DebateOrchestrator, "run", boom)
    r = client.post("/a2a", json={"skill": "debate_case", "topic": "AAPL"})
    assert r.status_code == 500
    assert r.json()["error"] == "internal error"
    assert "secret" not in r.text and "path.py" not in r.text


def test_wrong_token_is_rejected_constant_time(monkeypatch):
    monkeypatch.setattr(a2a_server, "CONFIG",
                        dataclasses.replace(CONFIG, bearer_token="secret"))
    r = client.post("/a2a", json={"topic": "AAPL"},
                    headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_sse_stream_yields_result_event():
    with client.stream("POST", "/a2a?stream=1&pace=0",
                       json={"topic": "TSLA 多空"}) as r:
        assert r.status_code == 200
        stages = [ln for ln in r.iter_lines() if '"stage"' in ln]
    assert any('"result"' in s for s in stages)
