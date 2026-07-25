import asyncio
import copy

from backend.agents import (
    AuditAgent,
    BearAgent,
    BullAgent,
    ChairAgent,
    MacroAgent,
    RiskAgent,
)
from backend.llm import MockLLM, OpenAICompatLLM
from backend.models import AuditVerdict, Claim, evidence_from_result


ALLOWED = {
    "skill-corporate-action-adjustment-auditor",
    "skill-survivorship-universe-auditor",
    "skill-portfolio-liquidity-stress-test",
    "project-index-weight-change-study",
    "skill-factor-ranking-sage",
    "skill-model-hpo-evidence-driven",
}


def test_every_claim_cites_only_integrated_skills(evidence_fixture):
    agents = [
        BullAgent(MockLLM()),
        BearAgent(MockLLM()),
        MacroAgent(MockLLM()),
        RiskAgent(MockLLM()),
    ]
    claims = []
    for agent in agents:
        claims.extend(asyncio.run(agent.argue(evidence_fixture)))

    assert claims
    assert all(set(claim.skills_used) <= ALLOWED for claim in claims)
    for claim in claims:
        assert claim.evidence
        assert all(item.skill_id in ALLOWED for item in claim.evidence)
        assert all(item.dataset_hashes for item in claim.evidence)


def test_available_result_is_not_downgraded_by_an_unavailable_peer_skill(
    evidence_with_missing_factor,
):
    claims = asyncio.run(
        BullAgent(MockLLM()).argue(evidence_with_missing_factor)
    )

    assert claims
    assert claims[0].confidence > 0.35
    assert "证据不足" not in claims[0].text
    assert claims[0].skills_used == [
        "skill-corporate-action-adjustment-auditor"
    ]


def test_all_unavailable_results_are_described_as_uncertain(
    evidence_with_missing_factor,
):
    corporate = evidence_with_missing_factor.results[
        "skill-corporate-action-adjustment-auditor"
    ]
    corporate.status = "insufficient-evidence"
    corporate.findings = []

    claims = asyncio.run(
        BullAgent(MockLLM()).argue(evidence_with_missing_factor)
    )

    assert claims[0].confidence <= 0.35
    assert "证据不足" in claims[0].text


def test_analytic_results_without_domain_outcome_use_moderate_confidence(
    evidence_fixture,
):
    claim = asyncio.run(MacroAgent(MockLLM()).argue(evidence_fixture))[0]

    assert claim.confidence == 0.45


def test_audit_prefers_cited_domain_failure_over_uncited_missing_skill(
    evidence_with_missing_factor,
):
    corporate = evidence_with_missing_factor.results[
        "skill-corporate-action-adjustment-auditor"
    ]
    corporate.outcome = "fail"

    claims = asyncio.run(
        BullAgent(MockLLM()).argue(evidence_with_missing_factor)
    )
    verdicts = asyncio.run(
        AuditAgent(MockLLM()).audit(evidence_with_missing_factor, claims)
    )

    assert verdicts[0].status == "bad_data"
    assert verdicts[0].audit_skill == (
        "skill-corporate-action-adjustment-auditor"
    )


def test_successful_claim_without_specialized_auditor_is_not_marked_missing(
    evidence_fixture,
):
    claims = asyncio.run(BearAgent(MockLLM()).argue(evidence_fixture))
    verdicts = asyncio.run(
        AuditAgent(MockLLM()).audit(evidence_fixture, claims)
    )

    assert verdicts[0].status == "pass"
    assert verdicts[0].audit_skill == "skill-portfolio-liquidity-stress-test"
    assert "已成功执行" in verdicts[0].reason


def test_audit_does_not_turn_missing_evidence_into_pass(
    evidence_with_missing_survivorship,
):
    for skill_id in (
        "skill-portfolio-liquidity-stress-test",
        "skill-model-hpo-evidence-driven",
        "skill-corporate-action-adjustment-auditor",
    ):
        result = evidence_with_missing_survivorship.results[skill_id]
        result.status = "insufficient-evidence"
        result.findings = []
    claims = asyncio.run(
        RiskAgent(MockLLM()).argue(evidence_with_missing_survivorship)
    )
    verdicts = asyncio.run(
        AuditAgent(MockLLM()).audit(
            evidence_with_missing_survivorship,
            claims,
        )
    )

    assert any(item.status == "missing_evidence" for item in verdicts)
    assert not any(item.status == "thin_data" for item in verdicts)


def test_audit_does_not_turn_skill_error_into_pass(evidence_fixture):
    evidence = copy.deepcopy(evidence_fixture)
    failed = evidence.results["skill-survivorship-universe-auditor"]
    failed.status = "error"
    failed.findings = []
    failed.warnings = ["skill execution failed"]
    for skill_id in (
        "skill-portfolio-liquidity-stress-test",
        "skill-model-hpo-evidence-driven",
        "skill-corporate-action-adjustment-auditor",
    ):
        result = evidence.results[skill_id]
        result.status = "insufficient-evidence"
        result.findings = []

    claims = asyncio.run(RiskAgent(MockLLM()).argue(evidence))
    verdicts = asyncio.run(AuditAgent(MockLLM()).audit(evidence, claims))

    assert any(
        item.status == "missing_evidence"
        and item.audit_skill == "skill-survivorship-universe-auditor"
        for item in verdicts
    )


def test_agents_send_sync_llm_calls_to_worker_threads(
    monkeypatch,
    evidence_fixture,
):
    calls = []
    evidence_fixture.results[
        "skill-corporate-action-adjustment-auditor"
    ].outcome = "fail"

    async def fake_to_thread(func, *args, **kwargs):
        calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    claims = asyncio.run(BullAgent(MockLLM()).argue(evidence_fixture))
    asyncio.run(AuditAgent(MockLLM()).audit(evidence_fixture, claims))

    assert "argue" in calls
    assert "audit_reason" in calls


def test_claim_rebuttal_fields_are_backward_compatible():
    claim = Claim(id="bull-1", agent="Bull", side="bull", text="首轮")

    assert claim.kind == "position"
    assert claim.round == 1
    assert claim.responds_to == []


def test_agent_rebuttal_targets_claim_and_uses_integrated_evidence(
    evidence_fixture,
):
    bull = asyncio.run(BullAgent(MockLLM()).argue(evidence_fixture))[0]
    bear = asyncio.run(BearAgent(MockLLM()).argue(evidence_fixture))[0]
    target_verdict = AuditVerdict(
        claim_id=bear.id,
        status="pass",
        reason="通过",
    )

    rebuttal = asyncio.run(
        BullAgent(MockLLM()).rebut(
            evidence_fixture,
            bull,
            [bear],
            [target_verdict],
        )
    )[0]

    assert rebuttal.id == "bull-2"
    assert rebuttal.kind == "rebuttal"
    assert rebuttal.round == 2
    assert rebuttal.responds_to == ["bear-1"]
    assert "bear-1" in rebuttal.text
    assert set(rebuttal.skills_used) <= ALLOWED
    assert all(item.dataset_hashes for item in rebuttal.evidence)


def test_agent_rebuttal_streams_deltas(evidence_fixture):
    bull = asyncio.run(BullAgent(MockLLM()).argue(evidence_fixture))[0]
    bear = asyncio.run(BearAgent(MockLLM()).argue(evidence_fixture))[0]
    deltas = []

    rebuttals = asyncio.run(
        BullAgent(MockLLM()).rebut(
            evidence_fixture,
            bull,
            [bear],
            [],
            on_delta=deltas.append,
        )
    )

    assert "".join(deltas) == rebuttals[0].text


def test_rebut_prompt_contains_claims_audit_and_no_invention_rules():
    system, user = OpenAICompatLLM._rebut_prompt(
        side="bull",
        symbol="601628.SH",
        evidence=[{"skill_id": "skill-factor-ranking-sage"}],
        own_claim={"id": "bull-1", "text": "首轮原文"},
        targets=[{"id": "bear-1", "text": "对手原文"}],
        target_verdicts=[{"claim_id": "bear-1", "status": "pass"}],
    )

    assert "具体 claim_id" in system
    assert "不得只复述" in system
    assert "不得补写" in system
    assert "可以明确承认" in system
    assert "必须忠实引用" in system
    assert "outcome=null 是正常值" in system
    assert "不得扩展为方向信号" in system
    assert "findings 本身不等于异常" in system
    assert "bull-1" in user
    assert "bear-1" in user
    assert "对手原文" in user
    assert '"status": "pass"' in user


def test_null_outcome_is_not_promoted_to_a_proven_audit_failure(evidence_fixture):
    hpo = evidence_fixture.results["skill-model-hpo-evidence-driven"]
    claim = Claim(
        id="risk-1",
        agent="Risk",
        side="risk",
        text="参数搜索结果",
        evidence=[evidence_from_result(hpo)],
        skills_used=[hpo.skill_id],
    )

    verdict = asyncio.run(AuditAgent(MockLLM()).audit(evidence_fixture, [claim]))[0]

    assert verdict.status == "thin_data"
    assert "不能据此确认异常" in verdict.reason
    assert "独立确认" in verdict.remediation


def test_successful_analytic_skill_pass_does_not_claim_predictive_validation(
    evidence_fixture,
):
    factor = evidence_fixture.results["skill-factor-ranking-sage"]
    claim = Claim(
        id="macro-1",
        agent="Macro",
        side="macro",
        text="因子筛选结果",
        evidence=[evidence_from_result(factor)],
        skills_used=[factor.skill_id],
    )

    verdict = asyncio.run(AuditAgent(MockLLM()).audit(evidence_fixture, [claim]))[0]

    assert verdict.status == "pass"
    assert "不代表预测性" in verdict.reason


def test_chair_only_uses_audit_passed_rebuttals_for_disagreement():
    claims = [
        Claim(id="bull-1", agent="Bull", side="bull", text="多头首轮"),
        Claim(id="bear-1", agent="Bear", side="bear", text="空头首轮"),
        Claim(
            id="bull-2",
            agent="Bull",
            side="bull",
            text="有效回应",
            kind="rebuttal",
            round=2,
            responds_to=["bear-1"],
        ),
        Claim(
            id="bear-2",
            agent="Bear",
            side="bear",
            text="无效回应",
            kind="rebuttal",
            round=2,
            responds_to=["bull-1"],
        ),
    ]
    verdicts = [
        AuditVerdict(
            claim_id="bull-2", status="pass", reason="通过"
        ),
        AuditVerdict(
            claim_id="bear-2",
            status="missing_evidence",
            reason="资料不足",
            remediation="补齐资料。",
        ),
    ]

    result = asyncio.run(
        ChairAgent(MockLLM()).synthesize("601628.SH", claims, verdicts)
    )
    disagreement = result["open_disagreements"][0]

    assert "有效回应" in disagreement.bear_view
    assert "无效回应" not in disagreement.bull_view
    assert any("bear-2" in item for item in result["risk_boundaries"])
