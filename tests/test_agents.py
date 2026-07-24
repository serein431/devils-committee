import asyncio

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


def test_insufficient_result_is_described_as_uncertain(
    evidence_with_missing_factor,
):
    claims = asyncio.run(
        BullAgent(MockLLM()).argue(evidence_with_missing_factor)
    )

    assert claims
    assert claims[0].confidence <= 0.35
    assert "证据不足" in claims[0].text


def test_audit_does_not_turn_missing_evidence_into_pass(
    evidence_with_missing_survivorship,
):
    claims = asyncio.run(
        RiskAgent(MockLLM()).argue(evidence_with_missing_survivorship)
    )
    verdicts = asyncio.run(
        AuditAgent(MockLLM()).audit(
            evidence_with_missing_survivorship,
            claims,
        )
    )

    assert any(item.status == "thin_data" for item in verdicts)
