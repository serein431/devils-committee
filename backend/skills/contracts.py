"""JSON shapes that mirror the REAL QuantSkills outputs (verified 2026-07-23).

We keep these as plain builder functions so the mock SkillRunner emits payloads
with the same field names the real CLIs produce. When SKILL_MODE=cli, the real
`report.json` is parsed into these same keys — the rest of the engine is agnostic.

Grounding notes from the real repos:
  - survivorship-universe-auditor: reports "已证实的问题" (proven issues) and
    missing-evidence SEPARATELY; never writes missing evidence up as "pass".
  - intraday-data-quality-auditor: flags timestamp / gap / price / volume defects.
  - corporate-action-adjustment-auditor: split & cash-dividend consistency.
  - model-hpo-evidence-driven: evidence-driven HPO, guards over-fitting.
  - factor-ranking-sage: ranks/selects factors from local factor+label CSVs.
"""
from __future__ import annotations

from typing import Any


# --- factor / evidence producing skills ------------------------------------
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
    """skill-index-rebalance-event-study."""
    return {
        "skill": "skill-index-rebalance-event-study",
        "symbol": symbol,
        "event": event,
        "car_bps": car_bps,              # cumulative abnormal return
        "window": window,
        "n_events": n_events,
    }


def regime(model: str, tilt: str, rationale: str) -> dict[str, Any]:
    """skill-dalio-all-weather / skill-templeton-global-contrarian / us-sector-rotation."""
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
    """skill-intraday-data-quality-auditor / corporate-action-adjustment-auditor."""
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
