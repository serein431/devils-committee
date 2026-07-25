"""Shared evidence contracts for the six integrated QuantSkills.

The live path converts PandaData datasets, online CLI reports and verified
precomputed reports into ``DatasetArtifact``, ``MarketDataBundle`` and
``SkillResult``. The offline path uses the same dataclasses but is always marked
``mode="mock"`` and is not public evidence.

Grounding notes from the real repos:
  - survivorship-universe-auditor: reports "已证实的问题" (proven issues) and
    missing-evidence SEPARATELY; never writes missing evidence up as "pass".
  - corporate-action-adjustment-auditor: split & cash-dividend consistency.
  - model-hpo-evidence-driven: evidence-driven HPO, guards over-fitting.
  - factor-ranking-sage: ranks/selects factors from local factor+label CSVs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ResultStatus = Literal["success", "insufficient-evidence", "error"]
SourceMode = Literal["live", "cache", "precomputed", "mock"]


@dataclass(frozen=True)
class DatasetArtifact:
    """One immutable, content-addressed market dataset."""

    name: str
    method: str
    params: dict[str, Any]
    path: str
    sha256: str
    rows: int
    mode: Literal["live", "cache", "mock"]
    fetched_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MarketDataBundle:
    """Datasets and public warnings used by one research request."""

    symbol: str
    status: ResultStatus
    mode: Literal["live", "cache", "mock"]
    datasets: dict[str, DatasetArtifact] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def insufficient(cls, symbol: str, reason: str) -> "MarketDataBundle":
        return cls(symbol, "insufficient-evidence", "live", warnings=[reason])

    @property
    def dataset_hashes(self) -> list[str]:
        return sorted({artifact.sha256 for artifact in self.datasets.values()})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkillFinding:
    claim: str
    evidence_refs: list[str]
    confidence: float


@dataclass
class SkillResult:
    skill_id: str
    mode: SourceMode
    status: ResultStatus
    duration_ms: int
    dataset_hashes: list[str]
    outcome: Literal["pass", "fail", "warning"] | None = None
    assumptions: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    findings: list[SkillFinding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- Legacy plain-dict helpers ---------------------------------------------
# Kept only for compatibility with callers outside the six-Skill runner. The
# runtime integration uses the dataclasses above, not these helper dictionaries.
def factor_ranking(symbol: str, factors: list[dict[str, Any]]) -> dict[str, Any]:
    """skill-factor-ranking-sage: ranked factors with IC-style metrics."""
    return {
        "skill": "skill-factor-ranking-sage",
        "symbol": symbol,
        "ranked_factors": factors,       # [{name, ic, ir, rank, n_obs}]
        "note": "Ranked from local factor+label CSVs; research-only.",
    }


def liquidity_stress(symbol: str, adv_ratio: float, days_to_liquidate: float,
                     impact_bps: float) -> dict[str, Any]:
    """skill-portfolio-liquidity-stress-test."""
    return {
        "skill": "skill-portfolio-liquidity-stress-test",
        "symbol": symbol,
        "adv_participation": adv_ratio,          # position / average daily volume
        "days_to_liquidate": days_to_liquidate,
        "est_impact_bps": impact_bps,            # spread + sqrt impact
    }


def event_study(symbol: str, event: str, car_bps: float, window: str,
                n_events: int) -> dict[str, Any]:
    """Project-owned index weight-change study."""
    return {
        "skill": "project-index-weight-change-study",
        "symbol": symbol,
        "event": event,
        "car_bps": car_bps,              # cumulative abnormal return
        "window": window,
        "n_events": n_events,
    }


def regime(model: str, tilt: str, rationale: str) -> dict[str, Any]:
    """Return a generic legacy regime payload."""
    return {"skill": model, "tilt": tilt, "rationale": rationale}


# --- AUDIT skills (the killer feature) -------------------------------------
def survivorship_audit(symbol: str, proven_issues: list[str],
                       missing_evidence: list[str]) -> dict[str, Any]:
    """skill-survivorship-universe-auditor.

    Mirrors the real output-contract: proven issues and missing evidence are
    reported SEPARATELY; the tool never reports missing evidence as 'pass'.
    """
    if proven_issues:
        conclusion = "issues_found"
    elif missing_evidence:
        conclusion = "insufficient_evidence"    # explicitly NOT "pass"
    else:
        conclusion = "no_issue_found"
    return {
        "skill": "skill-survivorship-universe-auditor",
        "symbol": symbol,
        "proven_issues": proven_issues,          # 已证实的问题
        "missing_evidence": missing_evidence,    # 缺失证据（不等于通过）
        "conclusion": conclusion,
    }


def data_quality_audit(symbol: str, defects: list[str]) -> dict[str, Any]:
    """Legacy data-quality payload; not used by the six-Skill runner."""
    return {
        "skill": "skill-intraday-data-quality-auditor",
        "symbol": symbol,
        "defects": defects,              # timestamp/gap/price/volume issues
        "conclusion": "defects_found" if defects else "clean",
    }


def hpo_evidence_audit(symbol: str, overfit_signals: list[str],
                       n_trials: int) -> dict[str, Any]:
    """skill-model-hpo-evidence-driven: guards over-tuned / evidence-thin models."""
    return {
        "skill": "skill-model-hpo-evidence-driven",
        "symbol": symbol,
        "overfit_signals": overfit_signals,      # e.g. "IS/OOS gap", "n_trials >> n_obs"
        "n_trials": n_trials,
        "conclusion": "suspected_overfit" if overfit_signals else "robust",
    }
