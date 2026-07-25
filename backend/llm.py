"""Pluggable LLM layer.

LLM_MODE=mock (default): deterministic, persona-flavored phrasing derived from the
structured skill evidence. No key needed — the full debate reads naturally offline.

LLM_MODE=openai: an OpenAI-compatible endpoint configured with an explicit model
identifier and API key. The same high-level interface is used in both modes.

Agents talk to this via high-level methods (argue / audit_reason / chair_line) so
neither mode leaks prompt-engineering into the agent code.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from .config import CONFIG

# Persona voices — the "气质" the手册 leaves as a canvas; here are sane defaults.
PERSONAS = {
    "bull":  {"name": "Bull 多头", "voice": "寻找盈利、成长、估值和市场表现中的积极面，但不把历史表现写成预测"},
    "bear":  {"name": "Bear 空头", "voice": "寻找盈利放缓、估值压力、趋势走弱和流动性假设中的下行风险"},
    "macro": {"name": "Macro 宏观", "voice": "结合行业归属、相对指数表现和指数权重变化判断外部环境"},
    "risk":  {"name": "Risk 风控", "voice": "量化波动、回撤、现金流、流动性和数据可靠性风险"},
    "audit": {"name": "Audit 魔鬼代言人", "voice": "阴阳怪气地抓假证据，绝不把'没证据'说成'没问题'"},
    "chair": {"name": "Chair 主持", "voice": "克制收敛，只画分歧地图，不下结论"},
}

ROLE_FOCUS = {
    "bull": (
        "先回答这只股票当前有哪些可被证据支持的优势，优先讨论盈利成长、"
        "经营质量、估值条件、同行位置、资金和相对强势；不要把数据审计当成公司利好，"
        "也不要把股价上涨直接写成资金关注或基本面改善。分红记录和无保留审计意见"
        "不能写成长线持有价值或下行安全垫。"
    ),
    "bear": (
        "先回答这只股票当前的主要弱点，优先讨论盈利放缓、估值约束、"
        "趋势回撤、股东资本行为和下行情景；流动性只能作为其中一项风险，不能占满全文。"
        "缺少同行或历史估值分位时，不得直接断言估值昂贵、便宜或缺少安全垫。"
        "股东户数变化不能推断筹码从机构转向散户，也不能直接推出抛售压力。"
    ),
    "macro": (
        "只讨论行业同行、利率货币、指数相对表现和指数权重变化；"
        "只有宏观或行业样本支持时才能判断行业环境。个股跑赢指数不等于整个行业风格转强。"
        "个股在同行中的收益分位也不等于行业整体强势或市场风格转向。"
        "不要重复微观流动性压力测试，也不要把因子入选写成宏观结论。"
    ),
    "risk": (
        "给出风险水平和触发条件，优先量化波动、回撤、现金流与退出压力；"
        "数据审计只有在确实影响研究结论时才作为核心风险。股东户数变化只能说明"
        "集中度变化，不能推断投资者身份、持仓信心或未来抛售压力。"
    ),
}

_EVIDENCE_INTERPRETATION = (
    "字段语义必须严格遵守：status=success 只表示 Skill 成功执行；"
    "outcome 才是审计型 Skill 的 pass/fail/warning 领域判决。"
    "分析型 Skill 的 outcome=null 是正常值，不等于失败、资料缺失、未经运行或负面证据，"
    "也不能据此标记为通过。"
    "findings 本身不等于异常：分析型 Skill 的 findings 可以只是筛选或搜索结果；"
    "只有审计型 Skill 的 outcome=fail/warning 或明确异常字段才能写成异常。"
    "因子被筛选只证明它在给定样本和方法下被选中；除非证据明确提供对应指标，"
    "不得扩展为方向信号、短期动量、预测能力、跨期稳定性、因果机制、宏观风格或可交易性。"
    "参数搜索分数只描述给定验证流程，不等于独立确认、稳定有效或已经证实过拟合。"
    "流动性压力测试只适用于给定持仓、价差、参与率与期限假设，不能外推为宏观环境结论。"
    "project-company-fundamentals 优先使用最近披露的季度财务报表，快报只作补充；"
    "同比是最新季度与上年同季度累计口径比较，估算 ROE 已在 assumptions 标明年化方法；"
    "不得自行推断营收或利润变化由投资收益、赔付、准备金、产品结构或其他未提供原因造成；"
    "金融企业若未提供 cash_to_profit_ratio，就不得用经营现金流/利润倍数评价利润质量；"
    "project-valuation-snapshot 的 PE/PB 是快照估算，缺少同行或历史分位时不能单独判断贵或便宜；"
    "project-market-behavior 只描述历史收益、相对强弱、波动和回撤，不是未来涨跌预测。"
    "project-industry-comparison 的分位只代表当前同行样本位置；"
    "project-capital-flow 中融资、北向、龙虎榜和大宗交易属于不同群体，不得合并虚构净流入；"
    "project-ownership-and-capital-actions 中股东户数下降不自动等于利好；"
    "股东户数增减不能识别筹码由机构、大户或散户中的哪一方转移，也不能直接推出未来卖压；"
    "project-corporate-events 中管理层交流、公告和业绩预告不等于结果已经实现；"
    "历史分红与标准无保留审计意见不能单独写成长线持有安全垫；"
    "沪深300 PE/PB只是市场背景，不是同行估值分位，不能据此判断个股高估或低估；"
    "project-macro-environment 只提供环境背景，没有传导证据时不能直接推出个股方向。"
)


class MockLLM:
    """Deterministic phrasing. Reads like an argument; needs no API key."""

    mode = "mock"

    def argue(self, *, side: str, symbol: str, evidence: list[dict[str, Any]]) -> str:
        bits = []
        for e in evidence:
            m = e.get("metrics", {})
            if m:
                kv = ", ".join(f"{k}={v}" for k, v in list(m.items())[:3])
                bits.append(f"{e['summary']}（{kv}）")
            else:
                bits.append(e["summary"])
        joined = "；".join(bits) if bits else "没有可解释的 Skill 结果"
        # Distinct voice per side so even offline the six agents sound like people,
        # not one template. (Real openai mode gets these voices via system prompts.)
        if side == "bull":
            return f"{symbol} 的积极面主要在这里：{joined}。这些是经营、估值和市场状态线索，不自动等于未来上涨。"
        if side == "bear":
            return f"{symbol} 的主要弱点和下行情景是：{joined}。其中流动性只是约束之一，盈利、估值和趋势能否改善同样关键。"
        if side == "macro":
            return f"从行业与市场环境看 {symbol}：{joined}。这里判断的是外部环境和相对强弱，不替代公司基本面评价。"
        if side == "risk":
            return f"{symbol} 当前需要重点管理的风险是：{joined}。风险评价关注波动、回撤、现金流和退出条件，不等同于公司好坏。"
        return f"{symbol}：{joined}。"

    def argue_stream(
        self,
        *,
        side: str,
        symbol: str,
        evidence: list[dict[str, Any]],
    ) -> Iterator[str]:
        """Keep the streaming contract available in offline mode."""

        yield self.argue(side=side, symbol=symbol, evidence=evidence)

    def rebut(
        self,
        *,
        side: str,
        symbol: str,
        evidence: list[dict[str, Any]],
        own_claim: dict[str, Any],
        targets: list[dict[str, Any]],
        target_verdicts: list[dict[str, Any]],
    ) -> str:
        target_ids = "、".join(str(item["id"]) for item in targets)
        verdict_by_id = {
            str(item["claim_id"]): str(item["status"])
            for item in target_verdicts
        }
        statuses = "、".join(
            f"{item['id']}={verdict_by_id.get(str(item['id']), '未审计')}"
            for item in targets
        )
        summaries = "；".join(
            str(item.get("summary", "")) for item in evidence if item.get("summary")
        )
        return (
            f"回应 {target_ids}：对方结论成立的前提需要与已集成证据一致。"
            f"目前审计状态为 {statuses}；我的依据是 {summaries or '现有 Skill 结果'}。"
            "若该前提经审计成立，我承认对方这一点；否则不能据此扩大结论。"
        )

    def rebut_stream(
        self,
        *,
        side: str,
        symbol: str,
        evidence: list[dict[str, Any]],
        own_claim: dict[str, Any],
        targets: list[dict[str, Any]],
        target_verdicts: list[dict[str, Any]],
    ) -> Iterator[str]:
        yield self.rebut(
            side=side,
            symbol=symbol,
            evidence=evidence,
            own_claim=own_claim,
            targets=targets,
            target_verdicts=target_verdicts,
        )

    def audit_reason(self, *, status: str, symbol: str, detail: dict[str, Any]) -> str:
        findings = [
            str(item.get("claim"))
            for item in detail.get("findings", [])
            if isinstance(item, dict) and item.get("claim")
        ]
        warnings = [str(item) for item in detail.get("warnings", []) if item]
        explanation = "；".join(findings or warnings)
        if status == "pass":
            return "现有审计结果没有指出可发布的问题。"
        if status == "selection_bias":
            return f"选择偏差审计有发现：{explanation or '请查看对应 Skill 结果。'}"
        if status == "bad_data":
            return f"数据审计有发现：{explanation or '请查看对应 Skill 结果。'}"
        if status == "suspected_overfit":
            return f"调参审计有发现：{explanation or '请查看对应 Skill 结果。'}"
        if status == "thin_data":
            return f"证据不足：{explanation or '对应 Skill 没有足够结果。'}"
        if status == "missing_evidence":
            return f"资料缺失：{explanation or '关键数据集或 Skill 结果不可用，当前无法完成审计。'}"
        return "审计：状态未知。"

    def chair_line(self, *, symbol: str, kind: str, payload: Any) -> str:
        if kind == "overall_assessment":
            return (
                f"综合判断：{symbol} 的现有证据同时呈现经营与市场层面的积极线索和"
                "估值、波动或数据边界，当前属于分歧较大。优势与弱点应分别阅读，"
                "不能把审计状态当成个股评级，也不能从历史表现直接推出未来方向。"
            )
        return str(payload)


class OpenAICompatLLM:
    """DeepSeek / any OpenAI-compatible chat endpoint via httpx."""

    mode = "openai"

    def __init__(self) -> None:
        import httpx  # local import so mock mode needs no dep
        self._httpx = httpx
        self._client = httpx.Client(
            base_url=CONFIG.llm_base_url,
            headers={"Authorization": f"Bearer {CONFIG.llm_api_key}"},
            timeout=120.0,
        )

    def _chat(self, system: str, user: str, *, want_json: bool = False) -> str:
        body: dict[str, Any] = {
            "model": CONFIG.llm_model,
            "temperature": CONFIG.llm_temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if want_json:
            body["response_format"] = {"type": "json_object"}
        # Degrade gracefully: a rate-limit / content-filter / malformed response
        # must not crash the debate — return a safe placeholder and log it.
        try:
            r = self._client.post("/chat/completions", json=body)
            r.raise_for_status()
            choices = (r.json() or {}).get("choices") or []
            content = choices[0].get("message", {}).get("content") if choices else None
            if not content:
                raise ValueError("empty or malformed LLM response")
            return content
        except Exception as exc:
            logging.getLogger("devils-committee").warning(
                "LLM call failed: %s",
                type(exc).__name__,
            )
            return "（模型说明暂不可用；请直接查看下方 Skill 结果、数据来源和风险提示。）"

    def _chat_stream(self, system: str, user: str) -> Iterator[str]:
        body: dict[str, Any] = {
            "model": CONFIG.llm_model,
            "temperature": CONFIG.llm_temperature,
            "stream": True,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        emitted = False
        try:
            with self._client.stream(
                "POST",
                "/chat/completions",
                json=body,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if isinstance(line, bytes):
                        line = line.decode("utf-8", errors="replace")
                    line = str(line).strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    event = json.loads(payload)
                    choices = event.get("choices") or []
                    delta = choices[0].get("delta", {}) if choices else {}
                    content = delta.get("content")
                    if content:
                        emitted = True
                        yield str(content)
            if not emitted:
                raise ValueError("empty or malformed streaming LLM response")
        except Exception as exc:
            logging.getLogger("devils-committee").warning(
                "Streaming LLM call failed: %s",
                type(exc).__name__,
            )
            if emitted:
                yield "（模型输出中断；请以下方完整证据为准。）"
            else:
                yield "（模型说明暂不可用；请直接查看下方 Skill 结果、数据来源和风险提示。）"

    @staticmethod
    def _argue_prompt(
        *,
        side: str,
        symbol: str,
        evidence: list[dict[str, Any]],
    ) -> tuple[str, str]:
        p = PERSONAS[side]
        system = (
            f"你是投资辩论庭中的「{p['name']}」。风格：{p['voice']}。"
            f"{ROLE_FOCUS[side]}"
            "只解释给定的公司研究证据和 Skill 结果。不得补写未提供的指标、来源或调用。"
            "严禁给出买入/卖出/目标价/收益承诺；你是在帮小白理解，不是荐股。"
            f"{_EVIDENCE_INTERPRETATION}"
            "rows 是输入观察行数，不是公司行动或异常数量；finding_count 才是发现数量。"
            "outcome=fail 的证据不能被包装成多头支撑，只能说明风险、异常和待核对项。"
            "不得猜测异常由分红、拆股、配股等具体事件造成，也不得把少量异常升级成系统性偏差；"
            "除非证据明确给出原因或范围。数据异常不等同于公司基本面利空。"
            "不得使用‘说明要么……要么……’列举证据中不存在的原因，也不得把相对上涨写成资金流入。"
            "第一句必须直接判断自己负责维度是偏强、偏弱还是证据不足；"
            "随后用2到4个最重要指标解释，不要逐项复述全部工具状态。"
            "数据缺失仅在它会改变该维度判断时说明。用简体中文，3~5句，口语但有据。"
        )
        user = f"标的：{symbol}\n公司研究与审计证据：\n{json.dumps(evidence, ensure_ascii=False, indent=2)}"
        return system, user

    def argue(self, *, side: str, symbol: str, evidence: list[dict[str, Any]]) -> str:
        system, user = self._argue_prompt(
            side=side,
            symbol=symbol,
            evidence=evidence,
        )
        return self._chat(system, user)

    def argue_stream(
        self,
        *,
        side: str,
        symbol: str,
        evidence: list[dict[str, Any]],
    ) -> Iterator[str]:
        system, user = self._argue_prompt(
            side=side,
            symbol=symbol,
            evidence=evidence,
        )
        yield from self._chat_stream(system, user)

    @staticmethod
    def _rebut_prompt(
        *,
        side: str,
        symbol: str,
        evidence: list[dict[str, Any]],
        own_claim: dict[str, Any],
        targets: list[dict[str, Any]],
        target_verdicts: list[dict[str, Any]],
    ) -> tuple[str, str]:
        p = PERSONAS[side]
        system = (
            f"你是投资辩论庭中的「{p['name']}」，正在进行第二轮定向交叉质询。"
            f"风格：{p['voice']}。必须点名回应具体 claim_id，并指出对方论证依赖的具体前提；"
            "可以明确承认对方论据成立。不得只复述自己的首轮陈述。"
            "必须忠实引用或紧贴对方原文中的一个具体前提；对方没有主张的动量、因果、"
            "宏观环境或可交易性，不得擅自安到对方头上。"
            "只能使用给定的公司研究与审计证据，不得补写数据、指标、来源或 Skill 调用，"
            "也不得把审计未通过写成已通过。严禁给出买卖建议、目标价或收益承诺。"
            f"{_EVIDENCE_INTERPRETATION}"
            "用简体中文，2~4 句，先回应对方，再说明该回应如何改变或保留分歧。"
        )
        verdict_by_id = {
            str(item.get("claim_id")): item
            for item in target_verdicts
            if item.get("claim_id")
        }
        target_material = [
            {
                "claim_id": target.get("id"),
                "agent": target.get("agent"),
                "side": target.get("side"),
                "text": target.get("text"),
                "audit": verdict_by_id.get(str(target.get("id")), {
                    "status": "not_audited",
                }),
            }
            for target in targets
        ]
        user = (
            f"标的：{symbol}\n"
            f"自己的首轮陈述：\n{json.dumps(own_claim, ensure_ascii=False, indent=2)}\n"
            f"需要回应的对手原文及审计状态：\n"
            f"{json.dumps(target_material, ensure_ascii=False, indent=2)}\n"
            f"本轮允许引用的 QuantSkills 证据：\n"
            f"{json.dumps(evidence, ensure_ascii=False, indent=2)}"
        )
        return system, user

    def rebut(
        self,
        *,
        side: str,
        symbol: str,
        evidence: list[dict[str, Any]],
        own_claim: dict[str, Any],
        targets: list[dict[str, Any]],
        target_verdicts: list[dict[str, Any]],
    ) -> str:
        system, user = self._rebut_prompt(
            side=side,
            symbol=symbol,
            evidence=evidence,
            own_claim=own_claim,
            targets=targets,
            target_verdicts=target_verdicts,
        )
        return self._chat(system, user)

    def rebut_stream(
        self,
        *,
        side: str,
        symbol: str,
        evidence: list[dict[str, Any]],
        own_claim: dict[str, Any],
        targets: list[dict[str, Any]],
        target_verdicts: list[dict[str, Any]],
    ) -> Iterator[str]:
        system, user = self._rebut_prompt(
            side=side,
            symbol=symbol,
            evidence=evidence,
            own_claim=own_claim,
            targets=targets,
            target_verdicts=target_verdicts,
        )
        yield from self._chat_stream(system, user)

    def audit_reason(self, *, status: str, symbol: str, detail: dict[str, Any]) -> str:
        system = (
            f"你是「{PERSONAS['audit']['name']}」，一个独立审计 Agent。"
            "你的天职是抓其他 Agent 论据里的存活/选择偏差、坏数据、过拟合。"
            "绝不把'缺失证据'写成'通过'。"
            "当审计判定为 missing_evidence 时，只说明缺少哪些必要资料以及为什么无法完成检查；"
            "不得称为样本薄弱，也不得声称已经证实选择偏差。一句话给出结论与理由。"
        )
        user = f"标的：{symbol}\n审计判定：{status}\n审计器原始输出：{json.dumps(detail, ensure_ascii=False)}"
        return self._chat(system, user)

    def chair_line(self, *, symbol: str, kind: str, payload: Any) -> str:
        if kind == "overall_assessment":
            system = (
                f"你是「{PERSONAS['chair']['name']}」。根据四方陈述、交叉质询和审计状态，"
                "直接回答这只股票当前强在哪里、弱在哪里。第一句必须以“综合判断：”开头，"
                "并从偏积极、中性偏积极、分歧较大、中性偏谨慎、偏谨慎、证据不足中选择一个标签。"
                "优先总结盈利与经营质量、估值、市场相对强弱和主要风险；"
                "审计标记为证据不足的推断不得进入综合判断；"
                "内部 Skill 运行状态只有在会改变结论时才提。不得新增素材中没有的数据，"
                "不得给出买卖指令、目标价或收益承诺。用简体中文2到3句。"
            )
        else:
            system = (
                f"你是「{PERSONAS['chair']['name']}」。克制收敛，只呈现共识与未解分歧，"
                "标注风险边界，绝不下买卖结论。"
            )
        user = f"标的：{symbol}\n类型：{kind}\n素材：{json.dumps(payload, ensure_ascii=False)}"
        return self._chat(system, user)


def get_llm():
    if CONFIG.llm_mode == "mock":
        return MockLLM()
    if CONFIG.llm_mode == "openai":
        if not CONFIG.llm_api_key.strip() or not CONFIG.llm_model.strip():
            raise RuntimeError("live LLM configuration unavailable")
        return OpenAICompatLLM()
    raise RuntimeError("unsupported LLM mode")
