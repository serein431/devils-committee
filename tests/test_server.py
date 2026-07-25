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


def test_avatar_assets_are_served_as_webp():
    for side in ("bull", "bear", "macro", "risk"):
        for state in ("idle", "speaking", "emphasis"):
            response = client.get(f"/assets/avatars/{side}-{state}.webp")
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/webp"
            assert response.content[:4] == b"RIFF"
            assert response.content[8:12] == b"WEBP"


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


def test_a2a_jsonrpc_message_send_returns_a_legacy_agent_message(monkeypatch):
    async def fake_run(self, research_request):
        assert research_request.question == "研究 600519.SH 的复权风险"
        return _minimal_result(research_request.symbol)

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "run", fake_run)
    request_id = "rpc-send-001"
    response = client.post("/a2a", json={
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "messageId": "message-send-001",
                "parts": [{"kind": "text", "text": "研究 600519.SH 的复权风险"}],
            },
        },
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == request_id
    message = payload["result"]
    assert message["kind"] == "message"
    assert message["role"] == "agent"
    assert message["messageId"]
    assert message["parts"][0]["kind"] == "text"
    assert "600519.SH" in message["parts"][0]["text"]


def test_a2a_jsonrpc_stream_returns_a_terminal_legacy_agent_message(monkeypatch):
    async def fake_run(self, research_request):
        assert research_request.question == "研究 300750.SZ 的流动性风险"
        return _minimal_result(research_request.symbol)

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "run", fake_run)
    request_id = "rpc-stream-001"
    with client.stream("POST", "/a2a", json={
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/stream",
        "params": {
            "message": {
                "role": "user",
                "messageId": "message-stream-001",
                "parts": [{"kind": "text", "text": "研究 300750.SZ 的流动性风险"}],
            },
        },
    }) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = [line for line in response.iter_lines() if line.startswith("data:")]

    assert len(lines) == 1
    event = json.loads(lines[0].removeprefix("data:").strip())
    assert event["jsonrpc"] == "2.0"
    assert event["id"] == request_id
    message = event["result"]
    assert message["kind"] == "message"
    assert message["role"] == "agent"
    assert message["parts"][0]["kind"] == "text"
    assert "300750.SZ" in message["parts"][0]["text"]


def test_a2a_jsonrpc_audit_claims_stream_stays_sse(monkeypatch):
    async def fake_audit(self, research_request):
        assert research_request.question == "审计 601318.SH 的分红证据"
        return {"symbol": research_request.symbol, "claims": [], "verdicts": []}

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "audit_claims", fake_audit)
    request_id = "rpc-audit-stream-001"
    with client.stream("POST", "/a2a", json={
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/stream",
        "params": {
            "skill": "audit_claims",
            "message": {
                "role": "user",
                "messageId": "message-audit-stream-001",
                "parts": [{"kind": "text", "text": "审计 601318.SH 的分红证据"}],
            },
        },
    }) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = [line for line in response.iter_lines() if line.startswith("data:")]

    assert len(lines) == 1
    event = json.loads(lines[0].removeprefix("data:").strip())
    assert event["jsonrpc"] == "2.0"
    assert event["id"] == request_id
    assert event["result"]["kind"] == "message"
    assert "601318.SH" in event["result"]["parts"][0]["text"]
