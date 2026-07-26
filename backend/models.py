"""Core data models shared across agents, orchestration, audit and compliance.

Pure stdlib dataclasses so the whole engine runs with zero third-party deps.
Shapes deliberately mirror the REAL QuantSkills contracts we verified on
2026-07-23 (see backend/skills/contracts.py) so the mock -> real swap is clean.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .skills.contracts import SkillResult

Side = Literal["bull", "bear", "macro", "risk"]
AuditStatus = Literal[
    "pass",              # audit found no proven issue
    "suspected_overfit", # model-hpo-evidence-driven: over-tuned / evidence-thin
    "selection_bias",    # survivorship-universe-auditor: cherry-picked universe
    "bad_data",          # intraday / corporate-action data-quality auditors
    "thin_data",         # not enough evidence to stand (NOT the same as "pass")
    "missing_evidence",  # a required dataset or skill result is unavailable
]


@dataclass(init=False)
class Evidence:
    """A claim-sized view of one real QuantSkill result."""

    skill_id: str
    summary: str
    status: str
    mode: str
    outcome: str | None = None
    dataset_hashes: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)

    def __init__(
        self,
        skill_id: str | None = None,
        summary: str = "",
        status: str = "success",
        mode: str = "mock",
        outcome: str | None = None,
        dataset_hashes: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        metrics: dict[str, Any] | None = None,
        assumptions: list[str] | None = None,
        *,
        skill: str | None = None,
    ) -> None:
        """Accept the former ``skill=`` name while exposing ``skill_id``."""

        if skill_id and skill and skill_id != skill:
            raise ValueError("skill_id and skill must match")
        resolved_skill = skill_id or skill
        if not resolved_skill:
            raise TypeError("skill_id is required")
        self.skill_id = resolved_skill
        self.summary = summary
        self.status = status
        self.mode = mode
        self.outcome = outcome
        self.dataset_hashes = list(dataset_hashes or [])
        self.evidence_refs = list(evidence_refs or [])
        self.metrics = dict(metrics or {})
        self.assumptions = list(assumptions or [])

    @property
    def skill(self) -> str:
        return self.skill_id

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["skill"] = self.skill_id
        return payload


def evidence_from_result(result: SkillResult) -> Evidence:
    """Project a SkillResult without adding claims, metrics or sources."""

    summaries = list(dict.fromkeys(item.claim for item in result.findings))
    if summaries:
        summary = "；".join(summaries[:2])
    elif result.outcome == "pass":
        summary = "该项检查已完成，未发现其定义范围内的问题"
    elif result.status == "success":
        summary = "该项检查已完成，详见指标与限制"
    else:
        summary = "该项没有可发布的结论"
    refs = sorted(
        {
            ref
            for item in result.findings
            for ref in item.evidence_refs
        }
    )
    return Evidence(
        skill_id=result.skill_id,
        summary=summary,
        status=result.status,
        mode=result.mode,
        outcome=result.outcome,
        dataset_hashes=list(result.dataset_hashes),
        evidence_refs=refs,
        metrics=dict(result.metrics),
        assumptions=list(result.assumptions),
    )


@dataclass
class Claim:
    id: str
    agent: str
    side: Side
    text: str
    confidence: float = 0.5          # agent's own stated confidence 0..1
    plain: str = ""                  # jargon-free one-liner for beginners (15 命门)
    evidence: list[Evidence] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)
    kind: Literal["position", "rebuttal"] = "position"
    round: int = 1
    responds_to: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["evidence"] = [e.to_dict() for e in self.evidence]
        # Internal source routing belongs to meta.skills_manifest. Keeping it
        # out of the user-facing claim prevents the UI from turning a stock
        # discussion back into a list of tool names.
        d["skills_used"] = []
        return d


@dataclass
class AuditVerdict:
    """The killer feature: an INDEPENDENT check of another agent's claim.

    Mirrors the survivorship-universe-auditor philosophy — never writes missing
    evidence up as 'pass'; missing evidence remains distinct from thin samples.
    """
    claim_id: str
    status: AuditStatus
    reason: str
    audit_skill: str = ""            # which QuantSkills auditor produced the verdict
    severity: Literal["none", "low", "medium", "high"] = "none"
    remediation: str = ""            # how the owning agent could fix / re-argue
    provenance: str = "mock"         # live | cache | precomputed | mock
    plain: str = ""                  # beginner analogy for the verdict (15 命门)

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DisagreementPoint:
    topic: str
    bull_view: str
    bear_view: str
    status: Literal["consensus", "open"] = "open"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DebateResult:
    """The full artifact. Two projections consume it:
      - A2A JSON response (track 18)
      - coach frontend render (track 15)
    """
    topic: str
    claims: list[Claim] = field(default_factory=list)
    verdicts: list[AuditVerdict] = field(default_factory=list)
    consensus: list[str] = field(default_factory=list)
    open_disagreements: list[DisagreementPoint] = field(default_factory=list)
    risk_boundaries: list[str] = field(default_factory=list)
    disclaimer: str = ""
    elapsed_sec: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def audit_flags(self) -> list[AuditVerdict]:
        return [v for v in self.verdicts if not v.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "claims": [c.to_dict() for c in self.claims],
            "verdicts": [v.to_dict() for v in self.verdicts],
            "audit_flags": [v.to_dict() for v in self.audit_flags()],
            "consensus": self.consensus,
            "open_disagreements": [d.to_dict() for d in self.open_disagreements],
            "risk_boundaries": self.risk_boundaries,
            "disclaimer": self.disclaimer,
            "elapsed_sec": self.elapsed_sec,
            "meta": self.meta,
        }
