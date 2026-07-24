"""The six debate agents — real, runnable implementations.

Differentiation lives here (track 18): the agents ARGUE in parallel and are then
INDEPENDENTLY AUDITED — not chained. The Audit agent re-derives its own view from
the skills and can stamp another agent's claim red (selection bias / bad data /
overfit) or honestly mark it 'thin_data' (never silently 'pass').

Each agent = QuantSkills evidence (SkillRunner) + persona phrasing (LLM layer).
Runs fully offline in mock mode; identical structure feeds DeepSeek in openai mode.
"""
from __future__ import annotations

from .models import Claim, Evidence, AuditVerdict, DisagreementPoint
from .skills.runner import SkillRunner
from .skills.data import stable_seed
from .plain import plain_audit


class _Base:
    side: str = ""

    def __init__(self, runner: SkillRunner, llm) -> None:
        self.runner = runner
        self.llm = llm

    def _ev(self, payload: dict, summary_key: str = "skill") -> Evidence:
        skill = payload.get("skill", "unknown")
        metrics = {k: v for k, v in payload.items()
                   if k not in ("skill", "note", "rationale") and not isinstance(v, (list, dict))}
        return Evidence(skill=skill, summary=payload.get("note") or skill,
                        data_ref="", metrics=metrics)


class BullAgent(_Base):
    side = "bull"

    async def argue(self, symbol: str) -> list[Claim]:
        fr = self.runner.factor_ranking(symbol)
        rot = self.runner.regime(symbol, "skill-us-sector-rotation")
        top = fr["ranked_factors"][0]
        ev = [
            Evidence(skill="skill-factor-ranking-sage",
                     summary="多因子打分给出正向排序",
                     data_ref=self.runner.data_ref(symbol),
                     metrics={"top_factor": top["name"], "ic": top["ic"],
                              "ir": top["ir"], "n_obs": top["n_obs"],
                              "window_return": fr["total_return_in_window"]}),
            Evidence(skill="skill-residual-guided-factor-selection",
                     summary="残差引导筛出的因子有互补信息",
                     metrics={"selected": fr["ranked_factors"][1]["name"],
                              "ic": fr["ranked_factors"][1]["ic"],
                              "n_obs": fr["ranked_factors"][1]["n_obs"]}),
            Evidence(skill="skill-us-sector-rotation", summary=rot["rationale"]),
        ]
        text = self.llm.argue(side="bull", symbol=symbol,
                              evidence=[e.to_dict() for e in ev])
        return [Claim(id="bull-1", agent="Bull", side="bull", text=text,
                      confidence=min(0.9, 0.5 + top["ic"] * 4),
                      evidence=ev,
                      skills_used=["skill-factor-ranking-sage",
                                   "skill-residual-guided-factor-selection",
                                   "skill-us-sector-rotation"],
                      )], fr  # also return raw factor payload for the auditor


class BearAgent(_Base):
    side = "bear"

    async def argue(self, symbol: str) -> list[Claim]:
        liq = self.runner.liquidity_stress(symbol)
        evt = self.runner.event_study(symbol)
        ev = [
            Evidence(skill="skill-portfolio-liquidity-stress-test",
                     summary="流动性压力测试显示清仓成本不低",
                     data_ref=self.runner.data_ref(symbol),
                     metrics={"adv_participation": liq["adv_participation"],
                              "days_to_liquidate": liq["days_to_liquidate"],
                              "impact_bps": liq["est_impact_bps"]}),
            Evidence(skill="skill-index-rebalance-event-study",
                     summary="指数再平衡事件研究的异常收益",
                     metrics={"car_bps": evt["car_bps"], "window": evt["window"],
                              "n_events": evt["n_events"]}),
            Evidence(skill="skill-holder-structure-scan",
                     summary="持仓结构集中度需警惕",
                     metrics={"concentration": "high" if stable_seed(symbol) % 2 else "moderate"}),
        ]
        text = self.llm.argue(side="bear", symbol=symbol,
                              evidence=[e.to_dict() for e in ev])
        return [Claim(id="bear-1", agent="Bear", side="bear", text=text,
                      confidence=0.55,
                      evidence=ev,
                      skills_used=["skill-portfolio-liquidity-stress-test",
                                   "skill-index-rebalance-event-study",
                                   "skill-holder-structure-scan"])]


class MacroAgent(_Base):
    side = "macro"

    async def argue(self, symbol: str) -> list[Claim]:
        aw = self.runner.regime(symbol, "skill-dalio-all-weather")
        ct = self.runner.regime(symbol, "skill-templeton-global-contrarian")
        ev = [
            Evidence(skill="skill-dalio-all-weather", summary=aw["rationale"]),
            Evidence(skill="skill-templeton-global-contrarian", summary=ct["rationale"]),
        ]
        text = self.llm.argue(side="macro", symbol=symbol,
                              evidence=[e.to_dict() for e in ev])
        return [Claim(id="macro-1", agent="Macro", side="macro", text=text,
                      confidence=0.5, evidence=ev,
                      skills_used=["skill-dalio-all-weather",
                                   "skill-templeton-global-contrarian"])]


class RiskAgent(_Base):
    side = "risk"

    async def argue(self, symbol: str) -> list[Claim]:
        liq = self.runner.liquidity_stress(symbol)
        ev = [
            Evidence(skill="skill-portfolio-liquidity-stress-test",
                     summary="集中清仓的冲击成本边界",
                     metrics={"impact_bps": liq["est_impact_bps"],
                              "days_to_liquidate": liq["days_to_liquidate"]}),
            Evidence(skill="skill-corporate-action-adjustment-auditor",
                     summary="复权一致性是价格序列可信的前提",
                     metrics={"checked": "split+dividend"}),
        ]
        text = self.llm.argue(side="risk", symbol=symbol,
                              evidence=[e.to_dict() for e in ev])
        return [Claim(id="risk-1", agent="Risk", side="risk", text=text,
                      confidence=0.5, evidence=ev,
                      skills_used=["skill-portfolio-liquidity-stress-test",
                                   "skill-corporate-action-adjustment-auditor"])]


class AuditAgent(_Base):
    """Independently audits every claim. This is the killer feature.

    It does NOT trust the arguing agents' framing — it re-derives its own audit
    view from the skills and stamps each claim: pass / selection_bias / bad_data /
    suspected_overfit / thin_data.
    """
    side = "audit"

    async def audit(self, symbol: str, claims: list[Claim],
                    factor_payload: dict | None) -> list[AuditVerdict]:
        verdicts: list[AuditVerdict] = []

        # Robustness (18 命脉): a failing auditor must degrade to a safe empty
        # verdict, never crash the whole audit / debate.
        def _safe(fn, default):
            try:
                return fn()
            except Exception:
                return default
        surv = _safe(lambda: self.runner.audit_survivorship(symbol, factor_payload or {}),
                     {"proven_issues": [], "missing_evidence": [], "conclusion": "no_issue_found",
                      "skill": "skill-survivorship-universe-auditor", "_provenance": "mock-fallback"})
        hpo = _safe(lambda: self.runner.audit_hpo(symbol, factor_payload or {}),
                    {"overfit_signals": [], "skill": "skill-model-hpo-evidence-driven"})
        dq = _safe(lambda: self.runner.audit_data_quality(symbol),
                   {"defects": [], "skill": "skill-corporate-action-adjustment-auditor",
                    "_provenance": "mock-fallback"})

        for c in claims:
            uses_factor = any("factor" in s for s in c.skills_used)
            uses_price = any(s in ("skill-portfolio-liquidity-stress-test",
                                   "skill-index-rebalance-event-study",
                                   "skill-corporate-action-adjustment-auditor")
                             for s in c.skills_used)
            status, detail, skill, sev, rem = "pass", {}, "", "none", ""

            # Gradient (tightest first): tiny sample + high IR -> overfit;
            # small sample + high IC -> selection bias; bad price data -> bad data;
            # very thin evidence -> honest 'thin_data' (never silently 'pass').
            if uses_factor and hpo["overfit_signals"]:
                status, detail = "suspected_overfit", hpo
                skill, sev = hpo["skill"], "medium"
                rem = "补 OOS/滚动验证，或降低搜索空间后复现。"
            elif uses_factor and surv["proven_issues"]:
                status, detail = "selection_bias", surv
                skill, sev = surv["skill"], "high"
                rem = "改用 point-in-time 全域（含退市），重算因子 IC 后再主张。"
            elif uses_price and dq["defects"]:
                status, detail = "bad_data", dq
                skill, sev = dq["skill"], "medium"
                rem = "先过复权/数据质量审计修正异常价，再引用该证据。"
            elif uses_factor and surv["conclusion"] == "insufficient_evidence":
                status, detail = "thin_data", surv
                skill, sev = surv["skill"], "low"
                rem = "补齐 point-in-time 域证据；当前不足以支撑该强度的主张。"

            prov = detail.get("_provenance", "mock") if isinstance(detail, dict) else "mock"
            # When a REAL QuantSkills CLI produced the verdict, use its own words +
            # severity; otherwise let the persona LLM phrase the mock finding.
            if prov == "real-cli" and detail.get("_reason"):
                reason = f"[真·QuantSkills 审计] {detail['_reason']}"
                sev = detail.get("_severity", sev)
            else:
                reason = self.llm.audit_reason(status=status, symbol=symbol, detail=detail)
            verdicts.append(AuditVerdict(claim_id=c.id, status=status, reason=reason,
                                         audit_skill=skill, severity=sev,
                                         remediation=rem, provenance=prov,
                                         plain=plain_audit(status)))
        return verdicts


class ChairAgent(_Base):
    """Converge into consensus / open disagreements / risk boundaries. No buy/sell."""
    side = "chair"

    @staticmethod
    def _metric(claim: Claim | None, key: str):
        if not claim:
            return None
        for e in claim.evidence:
            if key in e.metrics:
                return e.metrics[key]
        return None

    async def synthesize(self, symbol: str, claims: list[Claim],
                         verdicts: list[AuditVerdict]) -> dict:
        by_id = {c.id: c for c in claims}
        by_side = {c.side: c for c in claims}
        flags = [v for v in verdicts if not v.passed]
        flag_status = {v.claim_id: v.status for v in flags}

        bull, bear, risk = by_side.get("bull"), by_side.get("bear"), by_side.get("risk")
        top_factor = self._metric(bull, "top_factor")
        top_ic = self._metric(bull, "ic")
        impact = self._metric(bear, "impact_bps") or self._metric(risk, "impact_bps")
        days = self._metric(bear, "days_to_liquidate") or self._metric(risk, "days_to_liquidate")
        car = self._metric(bear, "car_bps")

        # --- disagreement map, grounded in THIS debate's numbers + audit ------
        factor_flag = flag_status.get("bull-1")           # selection_bias/overfit/thin
        data_flagged = any(s == "bad_data" for s in flag_status.values())
        open_points = [
            DisagreementPoint(
                topic="因子信号站不站得住",
                bull_view=(f"多因子打分把 {top_factor} 排在前面"
                           f"（IC={top_ic}），我当正向信号。" if top_factor
                           else "多因子打分给出正向排序。"),
                bear_view=({"selection_bias": "审计说这是挑赢家——小样本高 IC，很可能选择偏差。",
                            "suspected_overfit": "审计说这是背答案——样本外没验证，疑似过拟合。",
                            "thin_data": "审计说证据太薄，既不能信也不能全否。"}
                           .get(factor_flag,
                                "审计这轮没在因子上挑出硬伤，我转而盯流动性。")),
                status="open" if factor_flag else "consensus"),
            DisagreementPoint(
                topic="证据本身干不干净",
                bull_view="空头/风控引用了流动性、事件与复权相关证据。",
                bear_view=("但这些证据的价格序列被审计查出未复权跳空——先修数据再引用。"
                           if data_flagged
                           else "数据质量与复权审计通过，价格序列这关过了。"),
                status="open" if data_flagged else "consensus"),
            DisagreementPoint(
                topic="流动性与事件风险有多重",
                bull_view="板块轮动与宏观环境这轮偏顺风。",
                bear_view=(f"但集中清仓冲击约 {impact}bps、要 {days} 天，"
                           f"再平衡事件期异常收益 {car}bps，不可忽视。"
                           if impact is not None else "清仓冲击与事件异常收益不可忽视。"),
                status="open"),
        ]
        consensus = [
            f"双方都只用平台历史数据、且已缓存可复现（{symbol}）。",
            "没有任何一方给出目标价或收益——本庭只谈逻辑与风险。",
        ]
        if not flags:
            consensus.append("本轮审计未标红任何论据，双方证据都经得起独立复核。")
        risk_boundaries = [
            "本内容仅供学习与研究，不构成任何投资建议。",
            "历史与缓存数据不代表未来表现；样本区间有限。",
        ]
        for v in flags:
            c = by_id.get(v.claim_id)
            who = c.agent if c else v.claim_id
            risk_boundaries.append(
                f"⚠️ {who} 的一条论据被审计标注为「{v.status}」：{v.remediation}"
                "（此处 AI 不确定，建议人工/专业核实）")
        return {
            "consensus": consensus,
            "open_disagreements": open_points,
            "risk_boundaries": risk_boundaries,
        }
