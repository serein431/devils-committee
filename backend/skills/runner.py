"""SkillRunner — the single seam between agents and QuantSkills.

SKILL_MODE=mock (default): derive realistic, DETERMINISTIC skill outputs from the
(mock or real) daily bars, shaped exactly like the real CLIs' JSON. This is what
lets the full debate — including a red audit flag — run offline and reproducibly.

SKILL_MODE=cli: write inputs to CSV, invoke the real cloned skill CLIs
(`python scripts/<name>.py --input in.csv --out out.json`) and parse the report.
The rest of the engine never changes.

The audit methods intentionally sometimes FLAG a claim — that "stamp it red" moment
is the product's whole thesis (track 18). Flags are derived from evidence metrics,
not random, so the same topic always produces the same teaching moment.
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import CONFIG
from . import contracts
from .data import get_stock_daily, DailyBars, stable_seed


class SkillRunner:
    def __init__(self) -> None:
        self._bars_cache: dict[str, DailyBars] = {}

    # -- data -----------------------------------------------------------------
    def bars(self, symbol: str) -> DailyBars:
        if symbol not in self._bars_cache:
            self._bars_cache[symbol] = get_stock_daily(symbol)
        return self._bars_cache[symbol]

    def data_ref(self, symbol: str) -> str:
        b = self.bars(symbol)
        rng = f"{b.dates[0]}..{b.dates[-1]}" if b.dates else "n/a"
        return f"{symbol} {rng} ({b.source})"

    # =========================================================================
    # EVIDENCE-PRODUCING SKILLS (Bull / Bear / Macro / Risk)
    # =========================================================================
    def factor_ranking(self, symbol: str) -> dict[str, Any]:
        # REAL path: factors computed from real cross-sectional panel (DATA_MODE=panda).
        if CONFIG.data_mode == "panda":
            try:
                from ..quant import report as qreport
                ev = qreport.factor_evidence(symbol)
                out = contracts.factor_ranking(symbol, ev["ranked_factors"])
                out["total_return_in_window"] = round(self.bars(symbol).pct_change_total(), 4)
                out["_engine"] = "real-quant"
                out["in_universe"] = ev["in_universe"]
                out["universe_n"] = ev["universe_n"]
                return out
            except Exception as e:
                logging.getLogger("devils-committee").warning(
                    "real quant factor failed for %s (%s); using heuristic", symbol, str(e)[:100])
        b = self.bars(symbol)
        s = stable_seed(symbol)
        # Derived, deterministic factor table. n_obs deliberately varies so the
        # audit can legitimately catch a thin-evidence, high-IC factor.
        # Wide, deterministic spread so the audit genuinely DISCRIMINATES: some
        # symbols trip selection-bias, some overfit, some are clean. n_obs and ic
        # both span the audit thresholds (n<40 & ic>=0.05 => selection bias).
        s2 = stable_seed(symbol + "res")
        factors = [
            {"name": "momentum_12m", "ic": round(0.02 + (s % 50) / 1000, 3),
             "ir": round(0.4 + (s % 30) / 100, 2), "rank": 1, "n_obs": 60 + s % 60},
            {"name": "residual_reversal", "ic": round(0.03 + (s2 % 110) / 1000, 3),
             "ir": round(0.7 + (s2 % 70) / 100, 2), "rank": 2, "n_obs": 20 + s2 % 45},
            {"name": "quality_gross_profit", "ic": round(0.015 + (s % 20) / 1000, 3),
             "ir": round(0.3 + (s % 20) / 100, 2), "rank": 3, "n_obs": 900 + s % 200},
        ]
        out = contracts.factor_ranking(symbol, factors)
        out["total_return_in_window"] = round(b.pct_change_total(), 4)
        return out

    def liquidity_stress(self, symbol: str) -> dict[str, Any]:
        b = self.bars(symbol)
        s = stable_seed(symbol + "liq")
        avg_vol = sum(b.volume) / max(1, len(b.volume))
        adv_ratio = round(0.05 + (s % 60) / 100, 3)        # 5%..65% of ADV
        days = round(adv_ratio / 0.1, 1)
        impact = round(15 + (s % 120), 1)                   # 15..135 bps
        out = contracts.liquidity_stress(symbol, adv_ratio, days, impact)
        out["avg_daily_volume"] = round(avg_vol, 0)
        return out

    def event_study(self, symbol: str) -> dict[str, Any]:
        s = stable_seed(symbol + "evt")
        car = round(-120 + (s % 240), 1)                    # -120..+120 bps
        return contracts.event_study(symbol, "index_rebalance", car,
                                     "[-5,+5]", 8 + s % 20)

    def regime(self, symbol: str, model: str) -> dict[str, Any]:
        s = stable_seed(symbol + model)
        tilts = ["顺周期、风险偏好上行", "防御、后周期", "再通胀", "去通胀、看久期"]
        tilt = tilts[s % len(tilts)]
        return contracts.regime(
            model, tilt, f"该框架判断当前环境偏「{tilt}」；仅作研究背景，不构成判断。")

    # =========================================================================
    # AUDIT SKILLS (the differentiator) — independently judge others' claims
    # =========================================================================
    def audit_survivorship(self, symbol: str, factor_evidence: dict[str, Any]) -> dict[str, Any]:
        """Flag selection/survivorship bias. SKILL_MODE=cli runs the REAL auditor;
        on any failure it transparently falls back to the mock heuristic."""
        if CONFIG.skill_mode == "cli":
            try:
                return self._survivorship_cli(symbol)
            except Exception as e:                      # missing repo / bad schema / etc.
                out = self._survivorship_mock(symbol, factor_evidence)
                out["_provenance"] = "mock-fallback"
                out["_error"] = str(e)[:140]
                return out
        return self._survivorship_mock(symbol, factor_evidence)

    def _survivorship_cli(self, symbol: str) -> dict[str, Any]:
        import csv, os, tempfile
        from . import cli
        from .data import get_universe_rows
        rows, src = get_universe_rows(symbol)
        skill_dir = os.path.join(CONFIG.quantskills_dir, "skill-survivorship-universe-auditor")
        with tempfile.TemporaryDirectory() as td:
            in_csv, out_json = os.path.join(td, "u.csv"), os.path.join(td, "o.json")
            with open(in_csv, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader(); w.writerows(rows)
            real = cli.invoke(skill_dir, ["--input", in_csv, "--out", out_json])
        vf = cli.to_verdict_fields(real)
        proven = [vf["reason"]] if vf["status"] in ("selection_bias", "bad_data",
                                                    "suspected_overfit") else []
        missing = [vf["reason"]] if vf["status"] == "thin_data" else []
        conclusion = ("issues_found" if proven else
                      "insufficient_evidence" if missing else "no_issue_found")
        return {"skill": "skill-survivorship-universe-auditor", "symbol": symbol,
                "proven_issues": proven, "missing_evidence": missing,
                "conclusion": conclusion, "_provenance": "real-cli",
                "_universe_source": src, "_reason": vf["reason"],
                "_severity": vf["severity"]}

    def _survivorship_mock(self, symbol: str, factor_evidence: dict[str, Any]) -> dict[str, Any]:
        proven, missing = [], []
        for f in factor_evidence.get("ranked_factors", []):
            # High IC on a tiny sample = classic cherry-pick / survivorship risk.
            if f["ic"] >= 0.05 and f["n_obs"] < 40:
                proven.append(
                    f"Factor '{f['name']}' shows IC={f['ic']} on only n={f['n_obs']} "
                    f"obs — universe likely excludes delisted names (survivorship).")
            # Very thin sample with weak IC: not a proven bias, but not trustworthy.
            elif f["n_obs"] < 25 and f["ic"] < 0.05:
                missing.append(
                    f"Factor '{f['name']}' rests on only n={f['n_obs']} obs with weak "
                    f"IC={f['ic']} — too thin to either trust or refute.")
        if factor_evidence.get("total_return_in_window") is None:
            missing.append("No point-in-time universe membership provided; "
                           "cannot confirm delisting returns are included.")
        out = contracts.survivorship_audit(symbol, proven, missing)
        out["_provenance"] = "mock"
        return out

    def audit_data_quality(self, symbol: str) -> dict[str, Any]:
        """Bad-data / unadjusted-corporate-action audit. SKILL_MODE=cli runs the
        REAL corporate-action-adjustment-auditor; falls back to mock on failure."""
        if CONFIG.skill_mode == "cli":
            try:
                return self._data_quality_cli(symbol)
            except Exception as e:
                out = self._data_quality_mock(symbol)
                out["_provenance"] = "mock-fallback"
                out["_error"] = str(e)[:140]
                return out
        return self._data_quality_mock(symbol)

    def _data_quality_cli(self, symbol: str) -> dict[str, Any]:
        import csv, os, tempfile
        from . import cli
        from .data import get_adjustment_rows
        rows, src = get_adjustment_rows(symbol)
        skill_dir = os.path.join(CONFIG.quantskills_dir,
                                 "skill-corporate-action-adjustment-auditor")
        with tempfile.TemporaryDirectory() as td:
            in_csv, out_json = os.path.join(td, "ca.csv"), os.path.join(td, "o.json")
            with open(in_csv, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader(); w.writerows(rows)
            # 0.21: above BOTH the main-board ±10% and ChiNext/STAR ±20% daily limits,
            # so legitimate limit days are never false-flagged; only genuine unadjusted
            # corporate-action gaps (splits / 送转 / large special dividends) surface.
            real = cli.invoke(skill_dir, ["--input", in_csv, "--out", out_json,
                                          "--jump-threshold", "0.21"])
        vf = cli.to_verdict_fields(real)
        defects = [vf["reason"]] if vf["status"] != "pass" and real.get("findings") else []
        out = contracts.data_quality_audit(symbol, defects)
        out["skill"] = "skill-corporate-action-adjustment-auditor"
        out.update({"_provenance": "real-cli", "_source": src,
                    "_reason": vf["reason"], "_severity": vf["severity"]})
        return out

    def _data_quality_mock(self, symbol: str) -> dict[str, Any]:
        b = self.bars(symbol)
        defects = []
        # Deterministic 'defect' detection on the (mock) series.
        for i in range(1, b.n):
            if b.close[i - 1] > 0 and abs(b.close[i] / b.close[i - 1] - 1) > 0.11:
                defects.append(
                    f"{b.dates[i]}: {round((b.close[i]/b.close[i-1]-1)*100,1)}% jump "
                    f"— possible unadjusted corporate action or bad tick.")
            if len(defects) >= 2:
                break
        out = contracts.data_quality_audit(symbol, defects)
        # Name the same auditor the cli path actually runs, so the skills manifest
        # is consistent across mock/real: unadjusted jumps -> corporate-action auditor.
        out["skill"] = "skill-corporate-action-adjustment-auditor"
        out["_provenance"] = "mock"
        return out

    def audit_hpo(self, symbol: str, factor_evidence: dict[str, Any]) -> dict[str, Any]:
        signals = []
        facs = factor_evidence.get("ranked_factors", [])
        # REAL overfit: the factor report already ran an in/out-of-sample split.
        if factor_evidence.get("_engine") == "real-quant":
            for f in facs:
                if f.get("overfit"):
                    signals.append(f["overfit_reason"] or
                                   f"因子 {f['name']} 样本内外不一致，疑似过拟合。")
            out = contracts.hpo_evidence_audit(symbol, signals, n_trials=len(facs))
            out["_provenance"] = "real-quant"
            return out
        # heuristic fallback (mock data)
        best = max(facs, key=lambda f: f["ic"], default=None)
        if best and best["ir"] > 1.0 and best["n_obs"] < 30:
            signals.append(
                f"Best factor '{best['name']}' IR={best['ir']} with n={best['n_obs']} "
                f"— in-sample/out-of-sample gap unverified; likely over-tuned.")
        return contracts.hpo_evidence_audit(symbol, signals, n_trials=64)

    # =========================================================================
    # CLI MODE (real skills) — one shared helper, TODO(feishu) to wire fully
    # =========================================================================
    def _run_cli(self, skill: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Invoke a real cloned skill CLI via the shared adapter. SKILL_MODE=cli only."""
        import csv, os, tempfile
        from . import cli
        skill_dir = os.path.join(CONFIG.quantskills_dir, skill)
        with tempfile.TemporaryDirectory() as td:
            in_csv = os.path.join(td, "in.csv")
            out_json = os.path.join(td, "out.json")
            if rows:
                with open(in_csv, "w", newline="", encoding="utf-8") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                    w.writeheader()
                    w.writerows(rows)
                return cli.invoke(skill_dir, ["--input", in_csv, "--out", out_json])
            return cli.invoke(skill_dir, ["--demo"])   # no rows -> offline smoke
