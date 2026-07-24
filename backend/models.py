"""Core data models shared across agents, orchestration, audit and compliance.

Pure stdlib dataclasses so the whole engine runs with zero third-party deps.
Shapes deliberately mirror the REAL QuantSkills contracts we verified on
2026-07-23 (see backend/skills/contracts.py) so the mock -> real swap is clean.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal

Side = Literal["bull", "bear", "macro", "risk"]
AuditStatus = Literal[
    "pass",              # audit found no proven issue
    "suspected_overfit", # model-hpo-evidence-driven: over-tuned / evidence-thin
    "selection_bias",    # survivorship-universe-auditor: cherry-picked universe
    "bad_data",          # intraday / corporate-action data-quality auditors
    "thin_data",         # not enough evidence to stand (NOT the same as "pass")
]


@dataclass
class Evidence:
    """One piece of grounding behind a claim: which skill produced it + the numbers."""
    skill: str                       # e.g. "skill-factor-ranking-sage"
    summary: str                     # human-readable one-liner
    data_ref: str = ""               # e.g. "600519.SH 2019-01..2025-06 (cached)"
    metrics: dict[str, Any] = field(default_factory=dict)  # e.g. {"ic": 0.041, "n": 1180}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["evidence"] = [e.to_dict() for e in self.evidence]
        return d


@dataclass
class AuditVerdict:
    """The killer feature: an INDEPENDENT check of another agent's claim.

    Mirrors the survivorship-universe-auditor philosophy — never writes missing
    evidence up as 'pass'; 'thin_data' is a distinct, honest verdict.
    """
    claim_id: str
    status: AuditStatus
    reason: str
    audit_skill: str = ""            # which QuantSkills auditor produced the verdict
    severity: Literal["none", "low", "medium", "high"] = "none"
    remediation: str = ""            # how the owning agent could fix / re-argue
    provenance: str = "mock"         # mock | mock-fallback | real-cli — who computed it
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
