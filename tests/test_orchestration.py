"""Debate orchestration budgets, shared evidence and safe failure results."""

import asyncio
import copy

from backend import compliance
from backend.orchestration import (
    GLOBAL_BUDGET_SEC,
    MAX_AUDIT_ROUNDS,
    PER_AGENT_TIMEOUT_SEC,
    DebateOrchestrator,
    _extract_symbol,
)
from backend.research_request import ResearchRequest
from backend.skills.runner import SkillRunner


def test_extract_symbol_keeps_a_share_support_boundary():
    assert _extract_symbol("贵州茅台 600519 多空") == "600519.SH"
    assert _extract_symbol("分析 sz300750") == "300750.SZ"
    assert _extract_symbol("分析 WXYZ") == "WXYZ"
    assert _extract_symbol("帮我看看这个东西") == "UNKNOWN"


def test_budget_is_ten_minutes_with_two_minute_agent_limit():
    assert GLOBAL_BUDGET_SEC == 600
    assert PER_AGENT_TIMEOUT_SEC == 120
    assert MAX_AUDIT_ROUNDS == 1


def test_prepare_runs_once_for_all_agents(monkeypatch, evidence_fixture):
    calls = {"n": 0}

    async def prepare(self, request):
        calls["n"] += 1
        return evidence_fixture

    monkeypatch.setattr(SkillRunner, "prepare", prepare)
    result = asyncio.run(DebateOrchestrator().run("600519 多空"))

    assert calls["n"] == 1
    assert {claim.side for claim in result.claims} == {
        "bull",
        "bear",
        "macro",
        "risk",
    }
    assert result.meta["data_status"] == "success"


def test_research_request_is_accepted_without_reparsing(monkeypatch, evidence_fixture):
    request = ResearchRequest.from_payload(
        {"symbol": "600519.SH", "question": "检查流动性风险"}
    )
    seen = []

    async def prepare(self, received):
        seen.append(received)
        return evidence_fixture

    monkeypatch.setattr(SkillRunner, "prepare", prepare)
    result = asyncio.run(DebateOrchestrator().run(request))

    assert seen == [request]
    assert result.topic == request.question
    assert result.meta["start_date"] == request.start_date
    assert result.meta["end_date"] == request.end_date


def test_us_input_returns_structured_insufficient_evidence(monkeypatch):
    async def must_not_prepare(self, request):
        raise AssertionError("unsupported market must stop before data work")

    monkeypatch.setattr(SkillRunner, "prepare", must_not_prepare)
    result = asyncio.run(DebateOrchestrator().run("分析 WXYZ"))

    assert result.meta["symbol"] == "WXYZ"
    assert result.meta["data_status"] == "insufficient-evidence"
    assert result.meta["supported_market"] is False
    assert result.claims == []
    assert result.verdicts == []
    assert result.consensus == []
    assert result.open_disagreements == []
    assert result.disclaimer
    assert "当前真实研究只支持 A 股代码。" in result.risk_boundaries
    assert "当前结果没有使用模拟数据代替真实证据。" in result.risk_boundaries


def test_prepare_failure_does_not_expose_private_detail(monkeypatch):
    async def broken(self, request):
        raise RuntimeError("private service detail")

    monkeypatch.setattr(SkillRunner, "prepare", broken)
    result = asyncio.run(DebateOrchestrator().run("600519 多空"))

    assert result.meta["data_status"] == "error"
    assert result.claims == []
    assert "研究数据暂不可用，请稍后重试。" in result.risk_boundaries
    assert "private service detail" not in repr(result.to_dict())


def test_prepare_timeout_returns_public_timeout_message(monkeypatch):
    from backend import orchestration

    async def too_slow(self, request):
        await asyncio.sleep(0.05)

    monkeypatch.setattr(SkillRunner, "prepare", too_slow)
    monkeypatch.setattr(orchestration, "GLOBAL_BUDGET_SEC", 0.001)
    result = asyncio.run(DebateOrchestrator().run("600519 多空"))

    assert result.meta["data_status"] == "error"
    assert result.claims == []
    assert "研究请求超过内部时间限制。" in result.risk_boundaries


def test_non_success_bundle_returns_insufficient_evidence(
    monkeypatch,
    evidence_fixture,
):
    evidence = copy.deepcopy(evidence_fixture)
    evidence.bundle.status = "insufficient-evidence"
    evidence.results = {}

    async def prepare(self, request):
        return evidence

    monkeypatch.setattr(SkillRunner, "prepare", prepare)
    result = asyncio.run(DebateOrchestrator().run("600519 多空"))

    assert result.meta["data_status"] == "insufficient-evidence"
    assert result.claims == []
    assert "当前没有足够的授权数据支持研究。" in result.risk_boundaries


def test_all_unavailable_skills_return_empty_insufficient_evidence(
    monkeypatch,
    evidence_fixture,
):
    evidence = copy.deepcopy(evidence_fixture)
    for index, skill_result in enumerate(evidence.results.values()):
        skill_result.status = (
            "error" if index % 2 else "insufficient-evidence"
        )
        skill_result.findings = []
        skill_result.metrics = {}
        skill_result.warnings = ["required evidence unavailable"]

    async def prepare(self, request):
        return evidence

    monkeypatch.setattr(SkillRunner, "prepare", prepare)
    result = asyncio.run(DebateOrchestrator().run("600519 多空"))

    assert result.meta["data_status"] == "insufficient-evidence"
    assert result.claims == []
    assert result.verdicts == []
    assert result.consensus == []
    assert result.open_disagreements == []
    assert not any(
        verdict.status == "pass"
        for verdict in result.verdicts
    )
    manifest = result.meta["skills_manifest"]
    assert manifest["data"] == {
        "symbol": evidence.request.symbol,
        "status": evidence.bundle.status,
        "mode": evidence.bundle.mode,
        "dataset_hashes": evidence.bundle.dataset_hashes,
    }
    assert {
        item["skill_id"]: {
            "status": item["status"],
            "mode": item["mode"],
            "warnings": item["warnings"],
        }
        for item in manifest["results"]
    } == {
        skill_id: {
            "status": skill_result.status,
            "mode": skill_result.mode,
            "warnings": skill_result.warnings,
        }
        for skill_id, skill_result in evidence.results.items()
    }


def test_audit_claims_stops_when_all_skills_are_unavailable(
    monkeypatch,
    evidence_fixture,
):
    evidence = copy.deepcopy(evidence_fixture)
    for skill_result in evidence.results.values():
        skill_result.status = "insufficient-evidence"
        skill_result.findings = []
        skill_result.metrics = {}
        skill_result.warnings = ["required evidence unavailable"]

    async def prepare(self, request):
        return evidence

    monkeypatch.setattr(SkillRunner, "prepare", prepare)
    result = asyncio.run(DebateOrchestrator().audit_claims("审计 600519"))

    assert result["data_status"] == "insufficient-evidence"
    assert result["audits"] == []
    assert result["n_claims"] == 0
    manifest = result["skills_manifest"]
    assert manifest["data"] == {
        "symbol": evidence.request.symbol,
        "status": evidence.bundle.status,
        "mode": evidence.bundle.mode,
        "dataset_hashes": evidence.bundle.dataset_hashes,
    }
    assert {
        item["skill_id"]: {
            "status": item["status"],
            "mode": item["mode"],
            "warnings": item["warnings"],
        }
        for item in manifest["results"]
    } == {
        skill_id: {
            "status": skill_result.status,
            "mode": skill_result.mode,
            "warnings": skill_result.warnings,
        }
        for skill_id, skill_result in evidence.results.items()
    }


def test_one_publishable_skill_keeps_debate_and_marks_missing_claim_evidence(
    monkeypatch,
    evidence_fixture,
):
    evidence = copy.deepcopy(evidence_fixture)
    factor_skill = "skill-factor-ranking-sage"
    for skill_id, skill_result in evidence.results.items():
        if skill_id == factor_skill:
            continue
        skill_result.status = "insufficient-evidence"
        skill_result.findings = []
        skill_result.metrics = {}
        skill_result.warnings = ["required evidence unavailable"]

    async def prepare(self, request):
        return evidence

    monkeypatch.setattr(SkillRunner, "prepare", prepare)
    result = asyncio.run(DebateOrchestrator().run("600519 多空"))

    assert result.meta["data_status"] == "success"
    assert {claim.side for claim in result.claims} == {
        "bull",
        "bear",
        "macro",
        "risk",
    }
    assert len(result.verdicts) == len(result.claims)
    by_id = {claim.id: claim for claim in result.claims}
    for verdict in result.verdicts:
        claim = by_id[verdict.claim_id]
        if any(item.status != "success" for item in claim.evidence):
            assert verdict.status == "missing_evidence"
            assert "缺失" in verdict.reason


def test_one_agent_failure_only_removes_that_agents_claims(
    monkeypatch,
    evidence_fixture,
):
    async def prepare(self, request):
        return evidence_fixture

    async def broken(evidence):
        raise RuntimeError("private agent detail")

    monkeypatch.setattr(SkillRunner, "prepare", prepare)
    orchestrator = DebateOrchestrator()
    monkeypatch.setattr(orchestrator.bull, "argue", broken)
    result = asyncio.run(orchestrator.run("600519 多空"))

    assert {claim.side for claim in result.claims} == {"bear", "macro", "risk"}
    assert result.meta["data_status"] == "success"
    assert "private agent detail" not in repr(result.to_dict())


def test_four_research_agents_run_concurrently(monkeypatch, evidence_fixture):
    async def prepare(self, request):
        return evidence_fixture

    active = 0
    peak = 0

    async def concurrent_argue(evidence, on_delta=None):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return []

    monkeypatch.setattr(SkillRunner, "prepare", prepare)
    orchestrator = DebateOrchestrator()
    for agent in (
        orchestrator.bull,
        orchestrator.bear,
        orchestrator.macro,
        orchestrator.risk,
    ):
        monkeypatch.setattr(agent, "argue", concurrent_argue)

    asyncio.run(orchestrator.run("600519 多空"))

    assert peak == 4


def test_debate_audits_each_shared_evidence_claim(monkeypatch, evidence_fixture):
    async def prepare(self, request):
        return evidence_fixture

    monkeypatch.setattr(SkillRunner, "prepare", prepare)
    result = asyncio.run(DebateOrchestrator().run("600519 多空理由"))

    assert {verdict.claim_id for verdict in result.verdicts} == {
        claim.id for claim in result.claims
    }
    assert all(claim.plain for claim in result.claims)
    assert all(verdict.plain for verdict in result.audit_flags())


def test_stream_emits_detailed_claim_text_as_ordered_deltas(
    monkeypatch,
    evidence_fixture,
):
    async def prepare(self, request):
        return evidence_fixture

    async def collect_events():
        return [
            event
            async for event in DebateOrchestrator().stream(
                "600519 多空",
                pace=0,
            )
        ]

    monkeypatch.setattr(SkillRunner, "prepare", prepare)
    events = asyncio.run(collect_events())
    claims = {
        event["id"]: event
        for event in events
        if event.get("stage") == "claim"
    }
    starts = {
        event["id"]
        for event in events
        if event.get("stage") == "claim_start"
    }
    streamed = {}
    for event in events:
        if event.get("stage") == "claim_delta":
            streamed.setdefault(event["id"], []).append(event["delta"])

    assert starts == set(claims)
    assert set(streamed) == set(claims)
    for claim_id, claim in claims.items():
        assert "".join(streamed[claim_id]) == claim["text"]
        assert claim["plain"] not in "".join(streamed[claim_id])


def test_stream_forwards_llm_deltas_in_speaker_order(
    monkeypatch,
    evidence_fixture,
):
    from backend import orchestration

    class StreamingLLM:
        mode = "openai"

        def argue(self, **kwargs):
            return "这段整句回放不应出现"

        def argue_stream(self, *, side, symbol, evidence):
            yield f"{side}:真实-"
            yield "增量"

        def audit_reason(self, **kwargs):
            return "审计完成"

        def chair_line(self, **kwargs):
            return "主持完成"

    async def prepare(self, request):
        return evidence_fixture

    async def collect_events():
        return [
            event
            async for event in DebateOrchestrator().stream(
                "600519 多空",
                pace=0,
            )
        ]

    monkeypatch.setattr(SkillRunner, "prepare", prepare)
    monkeypatch.setattr(orchestration, "get_llm", lambda: StreamingLLM())
    events = asyncio.run(collect_events())

    starts = [event["side"] for event in events if event.get("stage") == "claim_start"]
    assert set(starts) == {"bull", "bear", "macro", "risk"}
    for side in starts:
        deltas = [
            event["delta"]
            for event in events
            if event.get("stage") == "claim_delta" and event.get("side") == side
        ]
        assert deltas == [f"{side}:真实-", "增量"]
        assert "".join(deltas) == next(
            event["text"]
            for event in events
            if event.get("stage") == "claim" and event.get("side") == side
        )


def test_skills_manifest_lists_real_result_contract(monkeypatch, evidence_fixture):
    async def prepare(self, request):
        return evidence_fixture

    monkeypatch.setattr(SkillRunner, "prepare", prepare)
    result = asyncio.run(DebateOrchestrator().run("600519 多空"))
    manifest = result.meta["skills_manifest"]

    assert manifest["data"] == {
        "symbol": "600519.SH",
        "status": "success",
        "mode": "mock",
        "dataset_hashes": ["daily-hash"],
    }
    assert manifest["all_skills"] == sorted(evidence_fixture.results)
    assert [item["skill_id"] for item in manifest["results"]] == sorted(
        evidence_fixture.results
    )
    factor = next(
        item
        for item in manifest["results"]
        if item["skill_id"] == "skill-factor-ranking-sage"
    )
    assert factor["used_by"] == ["Bull", "Macro"]
    assert factor["status"] == "success"
    assert factor["mode"] == "mock"
    assert factor["duration_ms"] == 1
    assert factor["dataset_hashes"] == ["daily-hash"]
    assert factor["assumptions"] == []
    assert factor["warnings"] == []
    assert result.meta["modes"] == ["mock"]
    assert result.meta["audit_engine"] == ["mock"]


def test_output_always_carries_compliance_fields(monkeypatch, evidence_fixture):
    async def prepare(self, request):
        return evidence_fixture

    monkeypatch.setattr(SkillRunner, "prepare", prepare)
    result = asyncio.run(DebateOrchestrator().run("600519 多空")).to_dict()

    assert result["disclaimer"]
    assert any("不构成" in boundary for boundary in result["risk_boundaries"])
    assert result["meta"]["gives_investment_advice"] is False
    assert result["meta"]["recommendation"] is None


def test_audit_claims_prepares_once_and_uses_public_contract(
    monkeypatch,
    evidence_fixture,
):
    calls = {"n": 0}

    async def prepare(self, request):
        calls["n"] += 1
        return evidence_fixture

    monkeypatch.setattr(SkillRunner, "prepare", prepare)
    result = asyncio.run(DebateOrchestrator().audit_claims("审计 600519 的多空论据"))

    assert calls["n"] == 1
    assert result["symbol"] == "600519.SH"
    assert result["data_status"] == "success"
    assert {item["claim_id"] for item in result["audits"]} == {
        "bull-1",
        "bear-1",
        "macro-1",
        "risk-1",
    }
    assert result["gives_investment_advice"] is False
    assert result["recommendation"] is None
    assert result["disclaimer"]
    for item in result["audits"]:
        assert item["provenance"] in {"live", "cache", "precomputed", "mock"}
        assert not compliance.find_violations(item["reason"] + item["claim"])


def test_audit_claims_failure_is_safe(monkeypatch):
    async def broken(self, request):
        raise RuntimeError("private audit service detail")

    monkeypatch.setattr(SkillRunner, "prepare", broken)
    result = asyncio.run(DebateOrchestrator().audit_claims("审计 600519"))

    assert result["symbol"] == "600519.SH"
    assert result["data_status"] == "error"
    assert result["audits"] == []
    assert "private audit service detail" not in repr(result)
