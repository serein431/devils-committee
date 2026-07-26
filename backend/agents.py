"""Debate agents that explain stock research profiles and challenge each other."""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Awaitable, Callable, Iterator

from .models import (
    AuditVerdict,
    Claim,
    DisagreementPoint,
    evidence_from_result,
)
from .plain import plain_audit
from .skills.research import (
    COMPANY_PROFILE_ID,
    EVENT_PROFILE_ID,
    FLOW_PROFILE_ID,
    FUNDAMENTAL_PROFILE_ID,
    INDUSTRY_PROFILE_ID,
    MACRO_PROFILE_ID,
    MARKET_PROFILE_ID,
    OWNERSHIP_PROFILE_ID,
    VALUATION_PROFILE_ID,
)
from .skills.runner import ResearchEvidence


ROLE_SKILLS = {
    "bull": [
        COMPANY_PROFILE_ID,
        FUNDAMENTAL_PROFILE_ID,
        VALUATION_PROFILE_ID,
        MARKET_PROFILE_ID,
        INDUSTRY_PROFILE_ID,
        FLOW_PROFILE_ID,
        OWNERSHIP_PROFILE_ID,
        EVENT_PROFILE_ID,
    ],
    "bear": [
        VALUATION_PROFILE_ID,
        FUNDAMENTAL_PROFILE_ID,
        MARKET_PROFILE_ID,
        INDUSTRY_PROFILE_ID,
        FLOW_PROFILE_ID,
        OWNERSHIP_PROFILE_ID,
        EVENT_PROFILE_ID,
    ],
    "macro": [
        COMPANY_PROFILE_ID,
        INDUSTRY_PROFILE_ID,
        MACRO_PROFILE_ID,
        MARKET_PROFILE_ID,
    ],
    "risk": [
        MARKET_PROFILE_ID,
        FUNDAMENTAL_PROFILE_ID,
        FLOW_PROFILE_ID,
        OWNERSHIP_PROFILE_ID,
        EVENT_PROFILE_ID,
    ],
}

# Compatibility for callers that construct ResearchEvidence directly without
# the project-owned stock profiles. Runtime SkillRunner always supplies them.
LEGACY_ROLE_SKILLS = {
    "bull": [
        "skill-factor-ranking-sage",
        "skill-corporate-action-adjustment-auditor",
    ],
    "bear": [
        "skill-portfolio-liquidity-stress-test",
        "project-index-weight-change-study",
    ],
    "macro": [
        "project-index-weight-change-study",
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

PROFILE_LABELS = {
    COMPANY_PROFILE_ID: "公司与行业背景",
    FUNDAMENTAL_PROFILE_ID: "财务与盈利",
    VALUATION_PROFILE_ID: "估值快照",
    MARKET_PROFILE_ID: "市场表现与风险",
    INDUSTRY_PROFILE_ID: "行业横向比较",
    FLOW_PROFILE_ID: "资金与交易情绪",
    OWNERSHIP_PROFILE_ID: "股东与资本行为",
    EVENT_PROFILE_ID: "公司事件",
    MACRO_PROFILE_ID: "宏观与行业环境",
}


def _public_research_evidence(item: Evidence) -> dict:
    """Give the debate model conclusions, never internal Skill telemetry."""

    return {
        "dimension": PROFILE_LABELS.get(item.skill_id, "补充研究资料"),
        "summary": item.summary,
        "metrics": dict(item.metrics),
        "assumptions": list(item.assumptions),
    }


def _claim_grounding_issue(claim: Claim) -> tuple[str, str] | None:
    """Catch recurring finance inferences that the supplied profiles cannot prove."""

    sentences = [
        sentence.strip()
        for sentence in re.split(r"[。！？\n]+", claim.text)
        if sentence.strip()
    ]
    safe_caveats = (
        "不能推断",
        "不能确认",
        "不能证明",
        "不能识别",
        "不能直接推出",
        "不能直接解读",
        "不能等同于",
        "无法判断",
        "不足以判断",
        "没有证据",
        "不得",
        "不等于",
        "未证明",
        "不支持",
    )
    for sentence in sentences:
        if any(token in sentence for token in safe_caveats):
            continue
        if (
            any(
                token in sentence
                for token in ("投资损益", "投资收益", "准备金", "赔付", "产品结构")
            )
            and any(token in sentence for token in ("归因", "导致", "指向", "由于", "源于", "可能"))
        ):
            return (
                "论据自行补写了财务数据未提供的利润变化原因；现有证据只能确认收入和利润变化，不能确认投资损益、准备金、赔付或产品结构的贡献。",
                "删除具体原因推断，只保留已披露的财务变化，或补充可核验的利润归因数据后重述。",
            )
        if (
            "股东户数" in sentence
            and any(
                token in sentence
                for token in (
                    "筹码从",
                    "向散户",
                    "机构或大户",
                    "长线资金",
                    "耐心不足",
                    "资金在离场",
                    "承接盘",
                    "锁定性",
                    "抛售压力",
                    "卖压",
                    "抛压",
                )
            )
        ):
            return (
                "股东户数变化只能说明持股集中度变化，不能识别筹码由哪类投资者转移，也不能直接推出未来抛售压力。",
                "将结论收窄为持股趋于集中或分散；若要判断投资者类型和卖压，需要独立持仓与交易数据。",
            )
        if any(token in sentence for token in ("小基数", "低基数")):
            return (
                "现有财务画像没有提供可验证的基数效应分析，不能把增长直接解释为或排除为小基数反弹。",
                "只报告营收和利润同比变化；补充上年同期绝对值、历史序列与业务拆分后再判断基数效应。",
            )
        if any(
            token in sentence
            for token in (
                "需求或备货预期",
                "需求很旺盛",
                "流向了库存",
                "流向库存",
                "流向了储能",
                "非车端领域",
            )
        ):
            return (
                "产量与装车量指标不能识别需求、备货、库存或储能去向，而且当月同比与累计同比并非同一时间口径。",
                "只陈述两个指标及口径差异，把需求消化和产品去向列为待验证问题。",
            )
        if any(
            token in sentence
            for token in (
                "大资金之间的换手",
                "大资金换手",
                "存量博弈",
                "资金面的合力",
                "资金合力",
                "恐慌出逃",
            )
        ):
            return (
                "融资、北向和大宗交易记录属于不同参与者与统计口径，不能合并推断大资金动机、换手性质或资金合力。",
                "分别报告各类资金指标，不推断参与者身份、情绪或交易目的。",
            )
        if any(token in sentence for token in ("市场风格确实", "市场风格在", "风格确实在往")):
            return (
                "个股相对指数和同行排名不能单独证明市场风格正在转向该股票或其行业。",
                "只描述个股相对强弱；补充行业整体收益、资金和宏观传导证据后再判断市场风格。",
            )
        if (
            "分红" in sentence
            and any(token in sentence for token in ("安全垫", "长期持有", "持有提供", "内部信心"))
        ):
            return (
                "分红记录与审计意见属于公司治理和历史分配事实，不能单独构成长线持有的安全垫。",
                "只陈述分红计划和审计意见，不外推为持有价值或下行保护。",
            )
        if (
            "回购" in sentence
            and any(token in sentence for token in ("内部信心", "承接意愿", "对冲", "支撑股价"))
        ):
            return (
                "回购记录只能说明已披露的公司行为，不能直接证明内部信心、承接意愿或对股价的支撑效果。",
                "只报告回购计划或进度；补充实施规模、成交价格和股本影响后再讨论其经济作用。",
            )
        if (
            any(token in sentence for token in ("估值", "PE", "PB"))
            and any(
                token in sentence
                for token in (
                    "极端高估",
                    "极端低估",
                    "估值压力",
                    "安全垫",
                    "安全边际",
                    "不构成负面拖累",
                    "不支持它被高估",
                    "估值合理",
                    "溢价有它的合理性",
                    "溢价合理",
                    "脱离基本面的炒作",
                )
            )
            and "是否" not in sentence
        ):
            return (
                "当前估值画像缺少同行估值和历史分位，不能据此确认高估、低估或安全垫。沪深300估值只提供市场背景，不是行业可比估值。",
                "仅报告PE/PB快照；补充同行和历史估值分位后再判断估值状态。",
            )
        if any(token in sentence for token in ("脆弱的持仓信心", "容易伴随快速反转")):
            return (
                "波动率和回撤可以量化价格风险，但不能直接证明持仓信心脆弱或未来容易快速反转。",
                "保留波动和回撤事实，把投资者信心或反转判断改为待验证情景。",
            )
        if any(token in sentence for token in ("只是短期反弹", "一次反弹", "视为反弹")):
            return (
                "历史收益、波动和回撤不能确认当前上涨只是反弹，也不能预测趋势持续性。",
                "只描述历史相对强弱与风险路径；若要判断反弹或趋势，需要额外的可验证规则。",
            )
        if "经营现金流" in sentence and any(
            token in sentence for token in ("主业造血", "现金创造能力", "盈利质量")
        ):
            return (
                "经营现金流变化不能直接写成主业造血能力或盈利质量结论，金融企业尤其需要使用行业专用现金流口径。",
                "只报告经营现金流同比，并结合行业专用报表字段后再解释经营质量。",
            )
        if any(
            token in sentence
            for token in ("数据可靠性没有发现问题", "数据可靠性没有问题", "数据完全可靠")
        ):
            return (
                "审计通过只表示已检查范围内没有发现问题，不能证明全部数据可靠或没有其他缺陷。",
                "把结论收窄为对应审计器定义范围内未发现问题，并保留未覆盖字段和事件的限制。",
            )
    return None


def _deterministic_overall_assessment(
    symbol: str,
    evidence: ResearchEvidence,
) -> str:
    profiles = evidence.analysis
    fundamental = profiles.get(FUNDAMENTAL_PROFILE_ID)
    market = profiles.get(MARKET_PROFILE_ID)
    industry = profiles.get(INDUSTRY_PROFILE_ID)
    flow = profiles.get(FLOW_PROFILE_ID)
    valuation = profiles.get(VALUATION_PROFILE_ID)
    positives: list[str] = []
    negatives: list[str] = []

    if fundamental and fundamental.status == "success":
        revenue = fundamental.metrics.get("revenue_yoy_pct")
        profit = fundamental.metrics.get("net_profit_yoy_pct")
        if isinstance(revenue, (int, float)):
            target = positives if revenue > 0 else negatives if revenue < 0 else None
            if target is not None:
                target.append(f"营收同比 {revenue:.2f}%")
        if isinstance(profit, (int, float)):
            target = positives if profit > 0 else negatives if profit < 0 else None
            if target is not None:
                target.append(f"归母净利润同比 {profit:.2f}%")

    if market and market.status == "success":
        recent_return = market.metrics.get("return_60d_pct")
        relative = market.metrics.get("relative_to_csi300_60d_pct")
        relative_label = "相对沪深300近60日"
        if not isinstance(relative, (int, float)):
            relative = market.metrics.get("relative_to_benchmark_13w_pct")
            relative_label = "相对市场默认基准近13周"
        volatility = market.metrics.get("volatility_60d_ann_pct")
        drawdown = market.metrics.get("max_drawdown_120d_pct")
        if isinstance(recent_return, (int, float)):
            target = positives if recent_return > 0 else negatives if recent_return < 0 else None
            if target is not None:
                target.append(f"近60日收益 {recent_return:.2f}%")
        if isinstance(relative, (int, float)):
            target = positives if relative > 0 else negatives if relative < 0 else None
            if target is not None:
                target.append(f"{relative_label} {relative:.2f} 个百分点")
        if isinstance(volatility, (int, float)) and volatility >= 30:
            negatives.append(f"60日年化波动 {volatility:.2f}%")
        if isinstance(drawdown, (int, float)) and drawdown <= -20:
            negatives.append(f"近120日最大回撤 {drawdown:.2f}%")

    if industry and industry.status == "success":
        percentile = industry.metrics.get("return_60d_percentile")
        if isinstance(percentile, (int, float)):
            if percentile >= 70:
                positives.append(f"同行近60日收益约 {percentile:.0f}% 分位")
            elif percentile <= 30:
                negatives.append(f"同行近60日收益约 {percentile:.0f}% 分位")

    if flow and flow.status == "success" and flow.metrics.get("direction") == "negative":
        negatives.append("资金面画像偏弱")

    if positives and negatives:
        label = "中性偏谨慎" if len(negatives) >= len(positives) + 2 else "分歧较大"
    elif positives:
        label = "中性偏积极"
    elif negatives:
        label = "偏谨慎"
    else:
        return f"综合判断：证据不足。{symbol} 当前缺少足够的可发布公司研究画像。"

    parts = [f"综合判断：{label}。听完四方，"]
    if positives and negatives:
        parts.append(
            "多头最有依据的部分是"
            + "、".join(positives[:3])
            + "；空头和风控更有力的提醒是"
            + "、".join(negatives[:4])
            + "。"
        )
    elif positives:
        parts.append(
            "多头提出的"
            + "、".join(positives[:3])
            + "在本轮占据上风，但这仍是已有数据下的阶段性判断。"
        )
    elif negatives:
        parts.append(
            "空头和风控提出的"
            + "、".join(negatives[:4])
            + "在本轮占据上风，积极观点还缺少足够反证。"
        )
    if valuation and valuation.status == "success":
        pe = valuation.metrics.get("pe_estimate")
        pb = valuation.metrics.get("pb_estimate")
        values = []
        if isinstance(pe, (int, float)):
            values.append(f"PE约 {pe:.2f} 倍")
        if isinstance(pb, (int, float)):
            values.append(f"PB约 {pb:.2f} 倍")
        if values:
            parts.append(
                "估值争论目前只能确认快照（"
                + "、".join(values)
                + "），缺少同行与历史分位时，主持人不把它归为贵或便宜。"
            )
    parts.append("这就是本轮交流收敛后的结论，而不是对未来涨跌的预测。")
    return "".join(parts)


def _dialogue_excerpt(text: str, limit: int = 105) -> str:
    cleaned = re.sub(r"\*\*", "", re.sub(r"\s+", " ", text)).strip()
    sentences = [
        item.strip()
        for item in re.split(r"(?<=[。！？])", cleaned)
        if item.strip()
    ]
    generic = ("我负责", "维度整体", "维度判断", "宏观环境这块", "证据不足，偏")
    excerpt = next(
        (
            item
            for item in sentences
            if (len(item) >= 28 or re.search(r"\d", item))
            and not (len(item) < 38 and any(token in item for token in generic))
        ),
        sentences[0] if sentences else cleaned,
    ).rstrip("。！？；")
    return excerpt if len(excerpt) <= limit else excerpt[:limit].rstrip("，；。") + "…"


def _conversation_overall_assessment(
    symbol: str,
    positions: list[Claim],
    rebuttals: list[Claim],
    verdict_by_claim: dict[str, AuditVerdict],
) -> str:
    by_side = {claim.side: claim for claim in positions}

    def accepted(side: str) -> bool:
        claim = by_side.get(side)
        verdict = verdict_by_claim.get(claim.id) if claim else None
        return bool(verdict and verdict.passed)

    if accepted("bull") and (accepted("bear") or accepted("risk")):
        label = "分歧较大"
        closing = "积极证据和下行风险同时成立，不能用单一的多头或空头叙事概括。"
    elif accepted("bull"):
        label = "中性偏积极"
        closing = "积极论据目前更完整，但仍需保留宏观和风险侧提出的边界。"
    elif accepted("bear") or accepted("risk"):
        label = "中性偏谨慎"
        closing = "风险论据目前更完整，积极观点还没有充分化解这些质疑。"
    else:
        label = "分歧较大"
        closing = "各方观点仍有审计保留，本轮只能确认争论焦点，不能把任何一方写成定论。"

    role_names = {
        "bull": "多头",
        "bear": "空头",
        "macro": "宏观",
        "risk": "风控",
    }
    clauses = []
    for side in ("bull", "bear", "macro", "risk"):
        claim = by_side.get(side)
        if claim is None:
            continue
        verdict = verdict_by_claim.get(claim.id)
        suffix = "" if verdict and verdict.passed else "，但审计仍有保留"
        clauses.append(
            f"{role_names[side]}的核心观点是{_dialogue_excerpt(claim.text)}{suffix}"
        )

    first_exchange = "；".join(clauses[:2])
    second_exchange = "；".join(clauses[2:])
    parts = [f"综合判断：{label}。听完四方，{first_exchange}。"]
    if second_exchange:
        parts.append(second_exchange + "。")
    if rebuttals:
        replies = "；".join(
            f"{role_names.get(claim.side, claim.agent)}回应称{_dialogue_excerpt(claim.text, 85)}"
            for claim in rebuttals[:2]
        )
        parts.append("第二轮里，" + replies + "。")
    parts.append("主持人的收束是：" + closing)
    return "".join(parts)


class _Base:
    side = ""

    def __init__(self, llm) -> None:
        self.llm = llm

    def _result_ids(self, evidence: ResearchEvidence) -> list[str]:
        return (
            ROLE_SKILLS[self.side]
            if evidence.analysis
            else LEGACY_ROLE_SKILLS[self.side]
        )

    async def argue(
        self,
        evidence: ResearchEvidence,
        on_delta: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> list[Claim]:
        all_results = evidence.all_results
        chosen = [
            all_results[skill_id]
            for skill_id in self._result_ids(evidence)
            if skill_id in all_results
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
        has_unverified_technical_analysis = any(
            item.skill_id not in PROFILE_LABELS
            and item.status == "success"
            and item.outcome is None
            for item in selected
        )
        public_evidence = [_public_research_evidence(item) for item in items]
        if insufficient:
            warnings = list(dict.fromkeys(
                warning
                for item in selected
                for warning in item.warnings
                if warning
            ))
            unavailable = "、".join(item.skill_id for item in selected)
            detail = f"（{'；'.join(warnings[:2])}）" if warnings else ""
            text = (
                f"证据不足：{unavailable} 当前没有可发布结果{detail}，"
                "因此无法对该维度形成方向性判断；这不代表风险或机会不存在，"
                "也不能据此推断市场处于某种状态。"
            )
            if on_delta is not None:
                await _call_delta(on_delta, text)
        elif on_delta is None:
            text = await asyncio.to_thread(
                self.llm.argue,
                side=self.side,
                symbol=evidence.request.symbol,
                evidence=public_evidence,
            )
        else:
            parts = []
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
                confidence=(
                    0.3
                    if insufficient
                    else 0.45
                    if has_domain_issue or has_unverified_technical_analysis
                    else 0.65
                ),
                evidence=items,
                skills_used=[item.skill_id for item in items],
            )
        ]

    async def rebut(
        self,
        evidence: ResearchEvidence,
        own_claim: Claim,
        targets: list[Claim],
        target_verdicts: list[AuditVerdict],
        on_delta: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> list[Claim]:
        if not targets:
            return []

        all_results = evidence.all_results
        chosen = [
            all_results[skill_id]
            for skill_id in self._result_ids(evidence)
            if skill_id in all_results
        ]
        available = [item for item in chosen if item.status == "success"]
        selected = available or chosen
        items = [evidence_from_result(item) for item in selected]
        if not items:
            return []

        llm_args = {
            "side": self.side,
            "symbol": evidence.request.symbol,
            "evidence": [_public_research_evidence(item) for item in items],
            "own_claim": {
                "id": own_claim.id,
                "side": own_claim.side,
                "text": own_claim.text,
            },
            "targets": [
                {
                    "id": target.id,
                    "agent": target.agent,
                    "side": target.side,
                    "text": target.text,
                }
                for target in targets
            ],
            "target_verdicts": [
                {
                    "claim_id": verdict.claim_id,
                    "status": verdict.status,
                    "plain": verdict.plain,
                }
                for verdict in target_verdicts
            ],
        }
        if on_delta is None:
            text = await asyncio.to_thread(self.llm.rebut, **llm_args)
        else:
            parts = []
            iterator = iter(self.llm.rebut_stream(**llm_args))
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
                id=f"{self.side}-2",
                agent=self.__class__.__name__.removesuffix("Agent"),
                side=self.side,
                text=text,
                confidence=own_claim.confidence,
                evidence=items,
                skills_used=[item.skill_id for item in items],
                kind="rebuttal",
                round=2,
                responds_to=[target.id for target in targets],
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
        all_results = evidence.all_results
        verdicts = []
        for claim in claims:
            grounding_issue = _claim_grounding_issue(claim)
            reason_override = ""
            remediation_override = ""
            unavailable_items = [
                item
                for item in claim.evidence
                if item.status in {"insufficient-evidence", "error"}
            ]
            unavailable_claim = min(
                unavailable_items,
                key=lambda item: (
                    item.status != "error",
                    item.skill_id not in AUDIT_STATUS,
                ),
                default=None,
            )
            relevant = [
                all_results[skill_id]
                for skill_id in AUDIT_STATUS
                if skill_id in all_results
                and skill_id in claim.skills_used
            ]
            successful_claim_results = [
                all_results[skill_id]
                for skill_id in claim.skills_used
                if skill_id in all_results
                and all_results[skill_id].status == "success"
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
                    and item.outcome in {"fail", "warning"}
                ),
                None,
            )
            indeterminate = next(
                (
                    item
                    for item in relevant
                    if item.status == "success" and item.outcome is None
                ),
                None,
            )
            if unavailable_claim is not None:
                status, source, severity = (
                    "missing_evidence",
                    all_results.get(unavailable_claim.skill_id),
                    "medium",
                )
            elif unavailable is not None:
                status, source, severity = (
                    "missing_evidence",
                    unavailable,
                    "medium",
                )
            elif flagged is not None:
                status = AUDIT_STATUS[flagged.skill_id]
                source, severity = flagged, "medium"
            elif grounding_issue is not None:
                status, source, severity = "thin_data", None, "medium"
                reason_override, remediation_override = grounding_issue
            elif indeterminate is not None:
                status, source, severity = "thin_data", indeterminate, "low"
            elif relevant:
                status, source, severity = "pass", None, "none"
            elif successful_claim_results:
                status, source, severity = (
                    "pass",
                    successful_claim_results[0],
                    "none",
                )
            else:
                status, source, severity = "missing_evidence", None, "medium"

            detail = source.to_dict() if source else {}
            if reason_override:
                reason = reason_override
            elif status == "pass":
                reason = (
                    f"{source.skill_id} 已成功执行并生成可追踪研究证据，当前论据没有引用不可用数据；"
                    "这里的通过只表示证据引用完整，不代表预测性、未来表现、因果性或可交易性已经验证。"
                    if source
                    else "现有独立审计结果没有指出可发布的问题。"
                )
            elif status == "thin_data" and source is not None and source.outcome is None:
                reason = (
                    f"{source.skill_id} 已成功生成分析结果，但没有提供 pass/fail/warning "
                    "领域判决；不能据此确认异常，也不能标记为领域验证通过。"
                )
            elif source is None:
                reason = (
                    "该论据引用的 Skill 当前没有映射到独立审计器，"
                    "因此不能标记为通过。"
                )
            else:
                reason = await asyncio.to_thread(
                    self.llm.audit_reason,
                    status=status,
                    symbol=evidence.request.symbol,
                    detail=detail,
                )
            if remediation_override:
                remediation = remediation_override
            elif status == "missing_evidence" and source is None:
                remediation = "接入与该论据对应的独立审计器后重新运行。"
            elif status == "thin_data" and source is not None and source.outcome is None:
                remediation = "补充明确的领域审计结论或独立确认结果。"
            elif status == "missing_evidence":
                remediation = "补齐缺失字段并重新运行对应 QuantSkill。"
            elif status != "pass":
                remediation = "核对引用的异常记录、输入口径与调整因子后重新运行。"
            else:
                remediation = ""
            verdicts.append(
                AuditVerdict(
                    claim_id=claim.id,
                    status=status,
                    reason=reason,
                    audit_skill=(
                        "project-grounding-guard"
                        if grounding_issue is not None and reason_override
                        else source.skill_id
                        if source
                        else ""
                    ),
                    severity=severity,
                    remediation=remediation,
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
        evidence: ResearchEvidence | None = None,
    ) -> dict:
        positions = [
            claim
            for claim in claims
            if claim.kind == "position" and claim.round == 1
        ]
        by_side = {claim.side: claim for claim in positions}
        verdict_by_claim = {verdict.claim_id: verdict for verdict in verdicts}
        accepted_positions = [
            claim
            for claim in positions
            if verdict_by_claim.get(claim.id) is not None
            and verdict_by_claim[claim.id].passed
        ]
        accepted_rebuttals = [
            claim
            for claim in claims
            if claim.kind == "rebuttal"
            and claim.round == 2
            and verdict_by_claim.get(claim.id) is not None
            and verdict_by_claim[claim.id].passed
        ]

        def view_with_rebuttals(claim: Claim | None) -> str:
            if claim is None:
                return "本轮没有陈述。"
            replies = [
                f"{reply.agent} 回应：{reply.text}"
                for reply in accepted_rebuttals
                if claim.id in reply.responds_to
            ]
            if not replies:
                return claim.text
            return f"{claim.text}\n第二轮回应：{' '.join(replies)}"

        bull = by_side.get("bull")
        bear = by_side.get("bear")
        risk = by_side.get("risk")
        flags = [verdict for verdict in verdicts if not verdict.passed]

        if positions:
            overall = _conversation_overall_assessment(
                symbol,
                positions,
                accepted_rebuttals,
                verdict_by_claim,
            )
        elif evidence is not None:
            overall = _deterministic_overall_assessment(symbol, evidence)
        else:
            overall = f"综合判断：证据不足。{symbol} 本轮没有形成可总结的四方发言。"
        overall_claim = Claim(
            id="chair-overall",
            agent="Chair",
            side="risk",
            text=overall,
        )
        if evidence is not None and _claim_grounding_issue(overall_claim) is not None:
            overall = _deterministic_overall_assessment(symbol, evidence)

        disagreements = []
        if bull or bear:
            disagreements.append(
                DisagreementPoint(
                    topic="多空证据分歧",
                    bull_view=(
                        view_with_rebuttals(bull)
                        if bull else "本轮没有多头陈述。"
                    ),
                    bear_view=(
                        view_with_rebuttals(bear)
                        if bear else "本轮没有空头陈述。"
                    ),
                    status="open",
                )
            )
        if risk:
            disagreements.append(
                DisagreementPoint(
                    topic="风险边界",
                    bull_view=view_with_rebuttals(risk),
                    bear_view="审计结果见风险提示。",
                    status="open" if flags else "consensus",
                )
            )

        consensus = [
            overall,
            f"评价范围：本轮只使用 {symbol} 的公司研究证据与审计结果，不补写缺失数据，也不提供具体价格预测、交易指令或收益承诺。",
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
