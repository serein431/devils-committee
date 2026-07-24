"""Debate agents that only explain existing QuantSkill results."""

from __future__ import annotations

from .models import (
    AuditVerdict,
    Claim,
    DisagreementPoint,
    evidence_from_result,
)
from .plain import plain_audit
from .skills.runner import ResearchEvidence


ROLE_SKILLS = {
    "bull": [
        "skill-factor-ranking-sage",
        "skill-corporate-action-adjustment-auditor",
    ],
    "bear": [
        "skill-portfolio-liquidity-stress-test",
        "skill-index-rebalance-event-study",
    ],
    "macro": [
        "skill-index-rebalance-event-study",
        "skill-factor-ranking-sage",
    ],
    "risk": [
        "skill-portfolio-liquidity-stress-test",
        "skill-model-hpo-evidence-driven",
        "skill-survivorship-universe-auditor",
        "skill-corporate-action-adjustment-auditor",
    ],
}

AUDIT_STATUS = {
    "skill-survivorship-universe-auditor": "selection_bias",
    "skill-model-hpo-evidence-driven": "suspected_overfit",
    "skill-corporate-action-adjustment-auditor": "bad_data",
}


class _Base:
    side = ""

    def __init__(self, llm) -> None:
        self.llm = llm

    async def argue(self, evidence: ResearchEvidence) -> list[Claim]:
        chosen = [
            evidence.results[skill_id]
            for skill_id in ROLE_SKILLS[self.side]
            if skill_id in evidence.results
        ]
        items = [evidence_from_result(item) for item in chosen]
        if not items:
            return []

        insufficient = any(item.status != "success" for item in chosen)
        text = self.llm.argue(
            side=self.side,
            symbol=evidence.request.symbol,
            evidence=[item.to_dict() for item in items],
        )
        if insufficient:
            text = f"证据不足：{text}"
        return [
            Claim(
                id=f"{self.side}-1",
                agent=self.__class__.__name__.removesuffix("Agent"),
                side=self.side,
                text=text,
                confidence=0.3 if insufficient else 0.65,
                evidence=items,
                skills_used=[item.skill_id for item in items],
            )
        ]


class BullAgent(_Base):
    side = "bull"


class BearAgent(_Base):
    side = "bear"


class MacroAgent(_Base):
    side = "macro"


class RiskAgent(_Base):
    side = "risk"


class AuditAgent(_Base):
    side = "audit"

    async def audit(
        self,
        evidence: ResearchEvidence,
        claims: list[Claim],
    ) -> list[AuditVerdict]:
        verdicts = []
        for claim in claims:
            relevant = [
                evidence.results[skill_id]
                for skill_id in AUDIT_STATUS
                if skill_id in evidence.results
                and (
                    skill_id in claim.skills_used
                    or claim.side in {"bull", "risk"}
                )
            ]
            thin = next(
                (
                    item
                    for item in relevant
                    if item.status == "insufficient-evidence"
                ),
                None,
            )
            flagged = next(
                (item for item in relevant if item.findings),
                None,
            )
            if thin is not None:
                status, source, severity = "thin_data", thin, "low"
            elif flagged is not None:
                status = AUDIT_STATUS[flagged.skill_id]
                source, severity = flagged, "medium"
            else:
                status, source, severity = "pass", None, "none"

            detail = source.to_dict() if source else {}
            verdicts.append(
                AuditVerdict(
                    claim_id=claim.id,
                    status=status,
                    reason=self.llm.audit_reason(
                        status=status,
                        symbol=evidence.request.symbol,
                        detail=detail,
                    ),
                    audit_skill=source.skill_id if source else "",
                    severity=severity,
                    remediation=(
                        "补齐缺失字段并重新运行对应 QuantSkill。"
                        if source
                        else ""
                    ),
                    provenance=source.mode if source else evidence.bundle.mode,
                    plain=plain_audit(status),
                )
            )
        return verdicts


class ChairAgent(_Base):
    """Keep the convergence API while only quoting debate and audit artifacts."""

    side = "chair"

    async def synthesize(
        self,
        symbol: str,
        claims: list[Claim],
        verdicts: list[AuditVerdict],
    ) -> dict:
        by_side = {claim.side: claim for claim in claims}
        bull = by_side.get("bull")
        bear = by_side.get("bear")
        risk = by_side.get("risk")
        flags = [verdict for verdict in verdicts if not verdict.passed]

        disagreements = []
        if bull or bear:
            disagreements.append(
                DisagreementPoint(
                    topic="多空证据分歧",
                    bull_view=bull.text if bull else "本轮没有多头陈述。",
                    bear_view=bear.text if bear else "本轮没有空头陈述。",
                    status="open",
                )
            )
        if risk:
            disagreements.append(
                DisagreementPoint(
                    topic="风险边界",
                    bull_view=risk.text,
                    bear_view="审计结果见风险提示。",
                    status="open" if flags else "consensus",
                )
            )

        consensus = [
            f"本轮只解释 {symbol} 的现有 Skill 结果，不补写缺失数据。",
            "本轮不给出目标价、买卖意见或收益承诺。",
        ]
        risk_boundaries = [
            "本内容仅供学习与研究，不构成任何投资建议。",
            "历史数据不代表未来表现，缺失结果必须补充后再判断。",
        ]
        for verdict in flags:
            risk_boundaries.append(
                f"{verdict.claim_id} 的审计状态为 {verdict.status}："
                f"{verdict.remediation}"
            )
        return {
            "consensus": consensus,
            "open_disagreements": disagreements,
            "risk_boundaries": risk_boundaries,
        }
