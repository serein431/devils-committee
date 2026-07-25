"""Debate agents that only explain existing QuantSkill results."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterator

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

    async def argue(
        self,
        evidence: ResearchEvidence,
        on_delta: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> list[Claim]:
        chosen = [
            evidence.results[skill_id]
            for skill_id in ROLE_SKILLS[self.side]
            if skill_id in evidence.results
        ]
        available = [item for item in chosen if item.status == "success"]
        selected = available or chosen
        items = [evidence_from_result(item) for item in selected]
        if not items:
            return []

        insufficient = not available
        has_domain_issue = any(
            item.outcome in {"fail", "warning"} for item in selected
        )
        public_evidence = [item.to_dict() for item in items]
        if on_delta is None:
            text = await asyncio.to_thread(
                self.llm.argue,
                side=self.side,
                symbol=evidence.request.symbol,
                evidence=public_evidence,
            )
            if insufficient:
                text = f"证据不足：{text}"
        else:
            parts = []
            if insufficient:
                prefix = "证据不足："
                parts.append(prefix)
                await _call_delta(on_delta, prefix)
            iterator = iter(
                self.llm.argue_stream(
                    side=self.side,
                    symbol=evidence.request.symbol,
                    evidence=public_evidence,
                )
            )
            while True:
                finished, delta = await asyncio.to_thread(
                    _next_stream_delta,
                    iterator,
                )
                if finished:
                    break
                if not delta:
                    continue
                parts.append(delta)
                await _call_delta(on_delta, delta)
            text = "".join(parts)
        return [
            Claim(
                id=f"{self.side}-1",
                agent=self.__class__.__name__.removesuffix("Agent"),
                side=self.side,
                text=text,
                confidence=(0.3 if insufficient else 0.45 if has_domain_issue else 0.65),
                evidence=items,
                skills_used=[item.skill_id for item in items],
            )
        ]


def _next_stream_delta(iterator: Iterator[str]) -> tuple[bool, str]:
    try:
        return False, str(next(iterator))
    except StopIteration:
        return True, ""


async def _call_delta(
    callback: Callable[[str], Awaitable[None] | None],
    delta: str,
) -> None:
    result = callback(delta)
    if inspect.isawaitable(result):
        await result


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
                and skill_id in claim.skills_used
            ]
            unavailable = next(
                (
                    item
                    for item in relevant
                    if item.status in {"insufficient-evidence", "error"}
                ),
                None,
            )
            flagged = next(
                (
                    item
                    for item in relevant
                    if item.findings
                    and (
                        item.outcome in {"fail", "warning"}
                        or item.outcome is None
                    )
                ),
                None,
            )
            if unavailable is not None:
                status, source, severity = (
                    "missing_evidence",
                    unavailable,
                    "medium",
                )
            elif flagged is not None:
                status = AUDIT_STATUS[flagged.skill_id]
                source, severity = flagged, "medium"
            else:
                status, source, severity = "pass", None, "none"

            detail = source.to_dict() if source else {}
            reason = await asyncio.to_thread(
                self.llm.audit_reason,
                status=status,
                symbol=evidence.request.symbol,
                detail=detail,
            )
            verdicts.append(
                AuditVerdict(
                    claim_id=claim.id,
                    status=status,
                    reason=reason,
                    audit_skill=source.skill_id if source else "",
                    severity=severity,
                    remediation=(
                        "补齐缺失字段并重新运行对应 QuantSkill。"
                        if status == "missing_evidence"
                        else "核对引用的异常记录、输入口径与调整因子后重新运行。"
                        if status != "pass"
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
