import asyncio
import copy

from backend.agents import AuditAgent, BearAgent, BullAgent, MacroAgent, RiskAgent
from backend.llm import MockLLM


ALLOWED = {
    "skill-corporate-action-adjustment-auditor",
    "skill-survivorship-universe-auditor",
    "skill-portfolio-liquidity-stress-test",
    "skill-index-rebalance-event-study",
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

    async def fake_to_thread(func, *args, **kwargs):
        calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    claims = asyncio.run(BullAgent(MockLLM()).argue(evidence_fixture))
    asyncio.run(AuditAgent(MockLLM()).audit(evidence_fixture, claims))

    assert "argue" in calls
    assert "audit_reason" in calls
