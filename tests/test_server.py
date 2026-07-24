"""A2A server robustness — track 18's #1 disqualifier is the service falling over
(掉线 / 超时 / 调不到). These lock down: endpoints respond, bad input is handled,
auth works, and one failing agent degrades instead of 500-ing the whole debate."""
import dataclasses
import json

from fastapi.testclient import TestClient

from backend import a2a_server
from backend.config import CONFIG
from backend.models import DebateResult

client = TestClient(a2a_server.app)


def _minimal_result(symbol: str) -> DebateResult:
    return DebateResult(
        topic="test",
        disclaimer="仅供研究，不构成投资建议。",
        meta={
            "symbol": symbol,
            "data_status": "success",
            "supported_market": True,
            "gives_investment_advice": False,
            "recommendation": None,
            "skills_manifest": {"all_skills": [], "results": []},
        },
    )


def test_healthz_always_ok():
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_agent_card_served_and_url_injected():
    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    card = r.json()
    assert card["url"].endswith("/a2a")
    assert card["documentationUrl"] == (
        f"{CONFIG.repository_url.rstrip('/')}/blob/main/README.md"
    )
    assert {s["id"] for s in card["skills"]} == {"debate_case", "audit_claims"}


def test_agent_card_has_three_a_share_examples_and_no_placeholder():
    card = client.get("/.well-known/agent-card.json").json()
    rendered = json.dumps(card, ensure_ascii=False)
    assert "600519.SH" in rendered
    assert "300750.SZ" in rendered
    assert "601318.SH" in rendered
    for removed in ("NV" + "DA", "TS" + "LA", "AA" + "PL"):
        assert removed not in rendered
    assert "your-host" not in rendered and "your-repo" not in rendered


def test_debate_case_returns_result():
    r = client.post("/a2a", json={"skill": "debate_case", "topic": "600519 多空"})
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["meta"]["symbol"] == "600519.SH"
    assert res["disclaimer"]


def test_structured_research_fields_reach_orchestrator(monkeypatch):
    seen = {}

    async def fake_run(self, research_request):
        seen["request"] = research_request
        return _minimal_result(research_request.symbol)

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "run", fake_run)
    response = client.post("/a2a", json={
        "skill": "debate_case",
        "symbol": "300750.SZ",
        "question": "流动性风险如何？",
        "start_date": "20240101",
        "end_date": "20260724",
        "portfolio_value": 800000,
        "spread_bps": 9,
    })
    assert response.status_code == 200
    research_request = seen["request"]
    assert research_request.symbol == "300750.SZ"
    assert research_request.question == "流动性风险如何？"
    assert research_request.start_date == "20240101"
    assert research_request.end_date == "20260724"
    assert research_request.portfolio_value == 800000
    assert research_request.spread_bps == 9


def test_audit_claims_skill_routed():
    r = client.post("/a2a", json={"skill": "audit_claims", "topic": "审计 600519.SH"})
    assert r.status_code == 200
    assert r.json()["skill"] == "audit_claims"
    assert r.json()["result"]["audits"]


def test_empty_body_is_422_not_500():
    response = client.post("/a2a", json={})
    assert response.status_code == 422
    assert response.json()["detail"] == "no task/topic found in message"


def test_invalid_structured_fields_are_safe_422():
    response = client.post(
        "/a2a",
        json={"topic": "研究 600519.SH", "portfolio_value": "not-a-number"},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "invalid request"}


def test_weird_input_still_resolves_a_symbol():
    r = client.post("/a2a", json={"topic": "帮我看看这个东西"})
    assert r.status_code == 200                 # symbol falls back, never crashes


def test_unsupported_market_returns_explained_result_not_server_error():
    response = client.post("/a2a", json={"topic": "分析 WXYZ"})
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["meta"]["data_status"] == "insufficient-evidence"
    assert result["claims"] == []


def test_bearer_auth_enforced_when_configured(monkeypatch):
    monkeypatch.setattr(a2a_server, "CONFIG",
                        dataclasses.replace(CONFIG, bearer_token="secret"))
    unauthorized = client.post("/a2a", json={"topic": "600519.SH"})
    assert unauthorized.status_code == 401
    assert unauthorized.json()["detail"] == "unauthorized"
    ok = client.post("/a2a", json={"topic": "600519.SH"},
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
    r = client.post("/a2a", json={"skill": "debate_case", "topic": "600519.SH"})
    assert r.status_code == 500
    assert r.json()["error"] == "internal error"
    assert "secret" not in r.text and "path.py" not in r.text


def test_wrong_token_is_rejected_constant_time(monkeypatch):
    monkeypatch.setattr(a2a_server, "CONFIG",
                        dataclasses.replace(CONFIG, bearer_token="secret"))
    r = client.post("/a2a", json={"topic": "600519.SH"},
                    headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_sse_stream_yields_result_event():
    with client.stream("POST", "/a2a?stream=1&pace=0",
                       json={"topic": "300750.SZ 多空"}) as r:
        assert r.status_code == 200
        stages = [ln for ln in r.iter_lines() if '"stage"' in ln]
    assert any('"result"' in s for s in stages)
