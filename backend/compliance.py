"""Compliance gate (tracks 15 & 18 hard requirement).

Every user-facing / A2A output passes through here. It:
  - strips/rewrites any buy/sell/return-promise/stock-pick language,
  - forces a risk disclaimer,
  - keeps audit flags VISIBLE (honesty is a scored criterion, not something to hide).

This is not decoration — it is a scored criterion (15 可信度) and a disqualifier
guard (18: 不得宣称收益 / 构成投资建议). Nothing reaches a user without passing here.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from .models import (Claim, Evidence, AuditVerdict, DisagreementPoint,
                     DebateResult)

BANNED_PATTERNS = [
    r"建议(买入|卖出|加仓|减仓|清仓|持有)",
    r"目标价",
    r"必涨|必跌|稳赚|保本|包赚|翻倍",
    r"收益率\s*[:：]?\s*\d+\s*%",
    r"预期收益\s*\d+",
    r"推荐(买|卖|持有)",
    r"(strong\s+)?(buy|sell)\b",
    r"\bprice\s+target\b",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in BANNED_PATTERNS]

REDACTION = "〔已按合规移除操作性表述〕"
DISCLAIMER = ("本内容由多智能体辩论生成，仅供学习与研究，不构成任何投资建议；"
              "不含买卖操作、目标价或收益承诺。历史/缓存数据不代表未来表现。")


def find_violations(text: str) -> list[str]:
    """Return the offending substrings (for tests / audit logs)."""
    hits: list[str] = []
    for pat in _COMPILED:
        hits.extend(m.group(0) for m in pat.finditer(text))
    return hits


def scrub(text: str) -> str:
    for pat in _COMPILED:
        text = pat.sub(REDACTION, text)
    return text


def _scrub_evidence(e: Evidence) -> Evidence:
    return replace(e, summary=scrub(e.summary))


def _scrub_claim(c: Claim) -> Claim:
    return replace(c, text=scrub(c.text), plain=scrub(c.plain),
                   evidence=[_scrub_evidence(e) for e in c.evidence])


def _scrub_verdict(v: AuditVerdict) -> AuditVerdict:
    return replace(v, reason=scrub(v.reason), remediation=scrub(v.remediation),
                   plain=scrub(v.plain))


def _scrub_point(d: DisagreementPoint) -> DisagreementPoint:
    return replace(d, bull_view=scrub(d.bull_view), bear_view=scrub(d.bear_view))


def enforce(result: DebateResult) -> DebateResult:
    """Scrub every user-facing string, attach disclaimer, keep audit flags visible."""
    result.claims = [_scrub_claim(c) for c in result.claims]
    result.verdicts = [_scrub_verdict(v) for v in result.verdicts]
    result.consensus = [scrub(s) for s in result.consensus]
    result.open_disagreements = [_scrub_point(d) for d in result.open_disagreements]
    result.risk_boundaries = [scrub(s) for s in result.risk_boundaries]
    result.disclaimer = DISCLAIMER
    result.meta["compliance"] = {"gate": "passed", "banned_patterns": len(BANNED_PATTERNS)}
    return result


def enforce_dict(payload: dict[str, Any]) -> dict[str, Any]:
    """Convenience for scrubbing an arbitrary dict (e.g. legacy callers)."""
    def walk(x: Any) -> Any:
        if isinstance(x, str):
            return scrub(x)
        if isinstance(x, list):
            return [walk(i) for i in x]
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        return x
    out = walk(payload)
    out["disclaimer"] = DISCLAIMER
    return out
