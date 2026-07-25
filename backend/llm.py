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
    "bull":  {"name": "Bull 多头", "voice": "寻找上行可能，但必须区分因子入选与方向、预测证据"},
    "bear":  {"name": "Bear 空头", "voice": "冷静挑刺，盯流动性、事件与持仓风险"},
    "macro": {"name": "Macro 宏观", "voice": "抽离个股，谈风格与环境背景"},
    "risk":  {"name": "Risk 风控", "voice": "只讲暴露、异常与合规边界，不站队"},
    "audit": {"name": "Audit 魔鬼代言人", "voice": "阴阳怪气地抓假证据，绝不把'没证据'说成'没问题'"},
    "chair": {"name": "Chair 主持", "voice": "克制收敛，只画分歧地图，不下结论"},
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
            return f"从上行角度看 {symbol}——{joined}。这些结果提供了讨论线索，但不自动等于方向或预测信号。"
        if side == "bear":
            return f"先别急着乐观。{symbol} 有几处我一直盯着的隐患：{joined}。上涨的故事得先过得了这几关。"
        if side == "macro":
            return f"把镜头拉远看 {symbol}：{joined}。个股的多空，得放进这个环境里才站得住。"
        if side == "risk":
            return f"抛开谁对谁错，我只报 {symbol} 的敞口：{joined}。这些是边界，不是判断——越界了再好的逻辑也得让路。"
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
            "只解释给定的 Skill 结果。不得补写未提供的指标、来源或 Skill 调用。"
            "严禁给出买入/卖出/目标价/收益承诺；你是在帮小白理解，不是荐股。"
            f"{_EVIDENCE_INTERPRETATION}"
            "rows 是输入观察行数，不是公司行动或异常数量；finding_count 才是发现数量。"
            "outcome=fail 的证据不能被包装成多头支撑，只能说明风险、异常和待核对项。"
            "不得猜测异常由分红、拆股、配股等具体事件造成，也不得把少量异常升级成系统性偏差；"
            "除非证据明确给出原因或范围。数据异常不等同于公司基本面利空。"
            "用简体中文，3~5 句，口语但有据。"
        )
        user = f"标的：{symbol}\n量化证据（QuantSkills 输出）：\n{json.dumps(evidence, ensure_ascii=False, indent=2)}"
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
            "只能使用给定的、已集成 QuantSkills 证据，不得补写数据、指标、来源或 Skill 调用，"
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
