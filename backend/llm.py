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
    "bull":  {"name": "Bull 多头", "voice": "亢奋但要摆证据，聚焦上行逻辑与因子支撑"},
    "bear":  {"name": "Bear 空头", "voice": "冷静挑刺，盯流动性、事件与持仓风险"},
    "macro": {"name": "Macro 宏观", "voice": "抽离个股，谈风格与环境背景"},
    "risk":  {"name": "Risk 风控", "voice": "只讲暴露、异常与合规边界，不站队"},
    "audit": {"name": "Audit 魔鬼代言人", "voice": "阴阳怪气地抓假证据，绝不把'没证据'说成'没问题'"},
    "chair": {"name": "Chair 主持", "voice": "克制收敛，只画分歧地图，不下结论"},
}


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
            return f"我看好 {symbol}——{joined}，这些信号都往同一个方向指。别只盯着风险，机会也是证据说了算。"
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
            "证据里的 status 只表示 Skill 是否成功执行，outcome 才是领域检查的 pass/fail/warning。"
            "rows 是输入观察行数，不是公司行动或异常数量；finding_count 才是发现数量。"
            "outcome=fail 或存在 findings 时必须明确说明异常，绝不能写成全部验证通过。"
            "outcome=fail 的证据不能被包装成多头支撑，只能说明风险、异常和待核对项。"
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
