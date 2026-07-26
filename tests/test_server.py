"""A2A server robustness — track 18's #1 disqualifier is the service falling over
(掉线 / 超时 / 调不到). These lock down: endpoints respond, bad input is handled,
auth works, and one failing agent degrades instead of 500-ing the whole debate."""
import asyncio
import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from backend import a2a_server
from backend.config import CONFIG
from backend.models import DebateResult

client = TestClient(a2a_server.app)


@pytest.fixture(autouse=True)
def _clear_a2a_task_state():
    for name in ("_TASKS", "_TASK_RUNNERS", "_TASK_SUBSCRIBERS"):
        store = getattr(a2a_server, name, None)
        if store is not None:
            store.clear()
    yield
    for name in ("_TASKS", "_TASK_RUNNERS", "_TASK_SUBSCRIBERS"):
        store = getattr(a2a_server, name, None)
        if store is not None:
            store.clear()


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


def test_transcribe_accepts_raw_browser_audio(monkeypatch):
    monkeypatch.setattr(
        a2a_server.transcription,
        "transcribe_audio",
        lambda payload: "研究 300750 的波动风险" if len(payload) >= 100 else "",
    )

    response = client.post(
        "/api/transcribe",
        content=b"browser-audio" * 10,
        headers={"Content-Type": "audio/webm"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "研究 300750 的波动风险"}


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
    assert card["supportedInterfaces"][0]["url"].endswith("/a2a")
    assert card["documentationUrl"] == (
        f"{CONFIG.repository_url.rstrip('/')}/blob/main/README.md"
    )
    assert {s["id"] for s in card["skills"]} == {"debate_case", "audit_claims"}


def test_agent_card_has_normal_insufficient_and_risk_boundary_examples():
    card = client.get("/.well-known/agent-card.json").json()
    rendered = json.dumps(card, ensure_ascii=False)
    assert "600519.SH" in rendered
    assert "TSLA" in rendered
    assert "明日买卖指令" in rendered
    assert "your-host" not in rendered and "your-repo" not in rendered


def test_agent_card_declares_a2a_v1_jsonrpc_and_public_auth_consistently():
    card = client.get("/.well-known/agent-card.json").json()

    assert card["supportedInterfaces"] == [{
        "url": f"{CONFIG.public_url.rstrip('/')}/a2a",
        "protocolBinding": "JSONRPC",
        "protocolVersion": "1.0",
    }]
    assert "url" not in card
    assert "securitySchemes" not in card
    assert "securityRequirements" not in card
    rendered = json.dumps(card, ensure_ascii=False)
    assert "研究 TSLA 的流动性风险" in rendered
    assert "明日买卖指令" in rendered


def test_agent_card_declares_bearer_only_when_service_enforces_it(monkeypatch):
    monkeypatch.setattr(
        a2a_server,
        "CONFIG",
        dataclasses.replace(CONFIG, bearer_token="secret"),
    )

    card = client.get("/.well-known/agent-card.json").json()

    assert card["securitySchemes"]["bearer"] == {
        "httpAuthSecurityScheme": {"scheme": "Bearer"}
    }
    assert card["securityRequirements"] == [
        {"schemes": {"bearer": {"list": []}}}
    ]


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


def test_sse_accepts_query_topic_when_webview_strips_post_body(monkeypatch):
    async def fake_stream(self, research_request, pace=0):
        assert research_request.question == "600519.SH 灵光兼容测试"
        yield {
            "stage": "result",
            "result": _minimal_result(research_request.symbol).to_dict(),
        }

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "stream", fake_stream)
    with client.stream(
        "POST",
        "/a2a?stream=1&pace=0&skill=debate_case&topic=600519.SH%20%E7%81%B5%E5%85%89%E5%85%BC%E5%AE%B9%E6%B5%8B%E8%AF%95",
        content=b"",
        headers={"Content-Type": "application/json"},
    ) as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line.startswith("data:")]

    assert any('"stage": "result"' in event for event in events)


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


def _v1_request(
    method: str,
    text: str,
    *,
    configuration: dict | None = None,
    task_id: str | None = None,
    context_id: str | None = None,
) -> dict:
    params = {
        "message": {
            "messageId": f"input-{method}",
            "role": "ROLE_USER",
            "parts": [{"text": text}],
        },
        "metadata": {"skill": "debate_case"},
    }
    if configuration is not None:
        params["configuration"] = configuration
    if task_id is not None:
        params["message"]["taskId"] = task_id
    if context_id is not None:
        params["message"]["contextId"] = context_id
    return {
        "jsonrpc": "2.0",
        "id": f"rpc-{method}",
        "method": method,
        "params": params,
    }


def _v1_headers(version: str = "1.0") -> dict[str, str]:
    return {"A2A-Version": version}


def test_a2a_rejects_unsupported_protocol_version():
    response = client.post(
        "/a2a",
        json=_v1_request("SendMessage", "研究 600519.SH"),
        headers=_v1_headers("9.0"),
    )

    assert response.status_code == 200
    assert response.json()["error"] == {
        "code": -32009,
        "message": "Version not supported",
    }


def test_a2a_missing_version_header_uses_legacy_method_semantics(monkeypatch):
    called = False

    async def fake_run(self, research_request):
        nonlocal called
        called = True
        return _minimal_result(research_request.symbol)

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "run", fake_run)
    response = client.post(
        "/a2a",
        json=_v1_request("SendMessage", "研究 600519.SH"),
    )

    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32601
    assert called is False


def test_a2a_v1_send_message_returns_completed_task(monkeypatch):
    async def fake_run(self, research_request):
        assert research_request.question == "研究 600519.SH 的复权风险"
        return _minimal_result(research_request.symbol)

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "run", fake_run)
    response = client.post(
        "/a2a",
        json=_v1_request("SendMessage", "研究 600519.SH 的复权风险"),
        headers=_v1_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    task = payload["result"]["task"]
    assert payload["id"] == "rpc-SendMessage"
    assert task["id"]
    assert task["contextId"]
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert task["history"][0]["role"] == "ROLE_USER"
    assert task["history"][0]["parts"] == [
        {"text": "研究 600519.SH 的复权风险"}
    ]
    assert task["artifacts"][0]["parts"][0]["data"]["meta"]["symbol"] == "600519.SH"


@pytest.mark.parametrize(("history_length", "roles"), [(0, []), (1, ["ROLE_AGENT"])])
def test_a2a_v1_send_message_applies_configuration_history_length(
    monkeypatch,
    history_length,
    roles,
):
    async def fake_run(self, research_request):
        return _minimal_result(research_request.symbol)

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "run", fake_run)
    response = client.post(
        "/a2a",
        json=_v1_request(
            "SendMessage",
            "研究 600519.SH 的风险",
            configuration={"historyLength": history_length},
        ),
        headers=_v1_headers(),
    )

    task = response.json()["result"]["task"]
    assert [message["role"] for message in task["history"]] == roles


def test_a2a_v1_message_task_id_must_exist():
    response = client.post(
        "/a2a",
        json=_v1_request(
            "SendMessage",
            "继续研究 600519.SH",
            task_id="missing-task",
            context_id="missing-context",
        ),
        headers=_v1_headers(),
    )

    assert response.json()["error"] == {
        "code": -32001,
        "message": "Task not found",
    }


def test_a2a_v1_message_task_id_requires_matching_context(monkeypatch):
    async def fake_run(self, research_request):
        return _minimal_result(research_request.symbol)

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "run", fake_run)
    first = client.post(
        "/a2a",
        json=_v1_request("SendMessage", "研究 600519.SH"),
        headers=_v1_headers(),
    ).json()["result"]["task"]
    response = client.post(
        "/a2a",
        json=_v1_request(
            "SendMessage",
            "继续研究 600519.SH",
            task_id=first["id"],
            context_id="wrong-context",
        ),
        headers=_v1_headers(),
    )

    assert response.json()["error"] == {
        "code": -32602,
        "message": "Invalid params",
    }


def test_a2a_v1_message_can_continue_matching_task(monkeypatch):
    async def fake_run(self, research_request):
        return _minimal_result(research_request.symbol)

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "run", fake_run)
    first = client.post(
        "/a2a",
        json=_v1_request("SendMessage", "研究 600519.SH"),
        headers=_v1_headers(),
    ).json()["result"]["task"]
    response = client.post(
        "/a2a",
        json=_v1_request(
            "SendMessage",
            "继续研究 600519.SH",
            task_id=first["id"],
            context_id=first["contextId"],
        ),
        headers=_v1_headers(),
    )

    task = response.json()["result"]["task"]
    assert task["id"] == first["id"]
    assert task["contextId"] == first["contextId"]
    assert [message["role"] for message in task["history"]] == [
        "ROLE_USER",
        "ROLE_AGENT",
        "ROLE_USER",
        "ROLE_AGENT",
    ]


def test_a2a_v1_stream_starts_with_task_and_finishes_with_status(monkeypatch):
    async def fake_stream(self, research_request, pace=0):
        yield {"stage": "data", "msg": "读取真实数据"}
        yield {"stage": "skills", "msg": "运行金融 Skills"}
        yield {"stage": "claim_start", "side": "bull", "agent": "Bull"}
        yield {"stage": "result", "result": _minimal_result(research_request.symbol).to_dict()}

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "stream", fake_stream)
    with client.stream(
        "POST",
        "/a2a",
        json=_v1_request("SendStreamingMessage", "研究 300750.SZ 的流动性风险"),
        headers=_v1_headers(),
    ) as response:
        assert response.status_code == 200
        events = [
            json.loads(line.removeprefix("data:").strip())
            for line in response.iter_lines()
            if line.startswith("data:")
        ]

    first = events[0]["result"]["task"]
    assert first["status"]["state"] == "TASK_STATE_SUBMITTED"
    updates = [event["result"]["statusUpdate"] for event in events if "statusUpdate" in event["result"]]
    assert any(update["status"]["state"] == "TASK_STATE_WORKING" for update in updates)
    assert updates[-1]["status"]["state"] == "TASK_STATE_COMPLETED"
    artifact_event = next(event["result"]["artifactUpdate"] for event in events if "artifactUpdate" in event["result"])
    assert artifact_event["lastChunk"] is True
    assert artifact_event["artifact"]["parts"][0]["data"]["meta"]["symbol"] == "300750.SZ"


def test_a2a_v1_get_task_returns_stored_task(monkeypatch):
    async def fake_run(self, research_request):
        return _minimal_result(research_request.symbol)

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "run", fake_run)
    sent = client.post(
        "/a2a",
        json=_v1_request("SendMessage", "研究 601318.SH 的风险证据"),
        headers=_v1_headers(),
    ).json()
    task_id = sent["result"]["task"]["id"]

    response = client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "rpc-get-001",
            "method": "GetTask",
            "params": {"id": task_id, "historyLength": 1},
        },
        headers=_v1_headers(),
    )

    assert response.status_code == 200
    task = response.json()["result"]
    assert task["id"] == task_id
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert len(task["history"]) == 1


def test_a2a_v1_get_task_returns_standard_not_found_error():
    response = client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "rpc-get-missing",
            "method": "GetTask",
            "params": {"id": "missing-task"},
        },
        headers=_v1_headers(),
    )

    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32001
    assert response.json()["error"]["message"] == "Task not found"


def test_a2a_v1_subscribe_to_terminal_task_returns_not_supported(monkeypatch):
    async def fake_run(self, research_request):
        return _minimal_result(research_request.symbol)

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "run", fake_run)
    task_id = client.post(
        "/a2a",
        json=_v1_request("SendMessage", "研究 600519.SH"),
        headers=_v1_headers(),
    ).json()["result"]["task"]["id"]
    response = client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "rpc-subscribe-terminal",
            "method": "SubscribeToTask",
            "params": {"id": task_id},
        },
        headers=_v1_headers(),
    )

    assert response.status_code == 200
    assert response.json()["error"] == {
        "code": -32004,
        "message": "Task not subscribable",
    }


def test_a2a_v1_subscribe_to_active_task_streams_until_terminal():
    async def scenario():
        task = a2a_server._new_task(
            {
                "messageId": "subscribe-input",
                "role": "ROLE_USER",
                "parts": [{"text": "研究 600519.SH"}],
            },
            skill="debate_case",
        )
        task_id = task["id"]
        a2a_server._set_task_status(
            task_id,
            "TASK_STATE_WORKING",
            "正在研究。",
        )
        response = await a2a_server._handle_v1({
            "jsonrpc": "2.0",
            "id": "rpc-subscribe-active",
            "method": "SubscribeToTask",
            "params": {"id": task_id},
        })
        first = json.loads((await anext(response.body_iterator)).removeprefix("data:"))
        a2a_server._complete_task(
            task_id,
            _minimal_result("600519.SH").to_dict(),
            skill="debate_case",
        )
        remaining = []
        async for raw in response.body_iterator:
            remaining.append(json.loads(raw.removeprefix("data:")))
        return first, remaining

    first, remaining = asyncio.run(scenario())
    assert first["result"]["statusUpdate"]["status"]["state"] == "TASK_STATE_WORKING"
    assert any("artifactUpdate" in event["result"] for event in remaining)
    assert remaining[-1]["result"]["statusUpdate"]["status"]["state"] == (
        "TASK_STATE_COMPLETED"
    )


def test_a2a_v1_cancel_task_cancels_return_immediately_task(monkeypatch):
    async def slow_run(self, research_request):
        await asyncio.sleep(60)
        return _minimal_result(research_request.symbol)

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "run", slow_run)
    with TestClient(a2a_server.app) as live_client:
        sent = live_client.post(
            "/a2a",
            json=_v1_request(
                "SendMessage",
                "研究 600519.SH 的风险",
                configuration={"returnImmediately": True},
            ),
            headers=_v1_headers(),
        ).json()
        task_id = sent["result"]["task"]["id"]

        response = live_client.post(
            "/a2a",
            json={
                "jsonrpc": "2.0",
                "id": "rpc-cancel-001",
                "method": "CancelTask",
                "params": {"id": task_id},
            },
            headers=_v1_headers(),
        )

    assert response.status_code == 200
    task = response.json()["result"]
    assert task["id"] == task_id
    assert task["status"]["state"] == "TASK_STATE_CANCELED"


def test_a2a_v1_stream_cancellation_emits_terminal_status(monkeypatch):
    async def slow_stream(self, research_request, pace=0):
        yield {"stage": "data", "msg": "读取数据"}
        await asyncio.sleep(60)

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "stream", slow_stream)

    async def scenario():
        request = _v1_request("SendStreamingMessage", "研究 600519.SH 的风险")
        message = request["params"]["message"]
        task = a2a_server._new_task(message, skill="debate_case")
        task_id = task["id"]
        research_request = a2a_server.extract_research_request(request)
        queue = asyncio.Queue()
        runner = asyncio.create_task(
            a2a_server._run_v1_streaming_task(
                task_id,
                research_request,
                skill="debate_case",
                queue=queue,
            )
        )
        a2a_server._TASK_RUNNERS[task_id] = runner
        await queue.get()
        await queue.get()
        a2a_server._cancel_task(task_id)
        runner.cancel()
        await runner
        remaining = []
        while True:
            event = await queue.get()
            if event is None:
                break
            remaining.append(event)
        return remaining

    remaining = asyncio.run(scenario())
    assert any(
        event["statusUpdate"]["status"]["state"] == "TASK_STATE_CANCELED"
        for event in remaining
    )


def test_a2a_v1_stream_registers_runner_before_first_event(monkeypatch):
    async def slow_stream(self, research_request, pace=0):
        await asyncio.sleep(60)
        if False:
            yield {}

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "stream", slow_stream)

    async def scenario():
        response = await a2a_server._handle_v1(
            _v1_request("SendStreamingMessage", "研究 600519.SH 的风险")
        )
        first = await anext(response.body_iterator)
        event = json.loads(first.removeprefix("data:").strip())
        task_id = event["result"]["task"]["id"]
        registered = task_id in a2a_server._TASK_RUNNERS
        runner = a2a_server._TASK_RUNNERS.get(task_id)
        if runner is not None:
            a2a_server._cancel_task(task_id)
            runner.cancel()
        await response.body_iterator.aclose()
        return registered

    assert asyncio.run(scenario()) is True
