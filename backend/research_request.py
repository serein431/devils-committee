"""Research request parsing and supported-market classification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

_NON_TICKER = {
    "BUY", "SELL", "HOLD", "NOW", "THE", "AND", "FOR", "VS", "US", "USD",
    "CNY", "AI", "IPO", "ETF", "CEO", "CFO", "PE", "PB", "EPS", "ROE",
    "ROI", "YOY", "Q1", "Q2", "Q3", "Q4", "A", "I", "OK", "WHY", "HOW",
}


def _previous_weekday(value: date) -> date:
    while value.weekday() >= 5:
        value -= timedelta(days=1)
    return value


def normalize_symbol(value: str) -> tuple[str, str]:
    raw = value.strip().upper()
    a_share = re.fullmatch(r"(?:(SH|SZ))?(\d{6})(?:\.(SH|SZ))?", raw)
    if a_share:
        prefix, digits, suffix = a_share.groups()
        exchange = suffix or prefix or ("SH" if digits.startswith("6") else "SZ")
        return f"{digits}.{exchange}", "cn"
    hk_share = re.fullmatch(r"(\d{1,5})\.HK", raw)
    if hk_share:
        digits = hk_share.group(1).lstrip("0") or "0"
        if len(digits) <= 4:
            return f"{digits.zfill(4)}.HK", "hk"
        return raw, "hk"
    if re.fullmatch(r"[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,4})?", raw):
        return raw, "us"
    return "UNKNOWN", "unknown"


def symbol_from_text(text: str) -> tuple[str, str]:
    malformed_a_share = re.search(
        r"(?i)(?<![A-Za-z0-9_])(?:sh|sz)?\d{1,5}\.(?:sh|sz)"
        r"(?![A-Za-z0-9_])",
        text,
    )
    if malformed_a_share:
        return "UNKNOWN", "unknown"
    candidate = re.search(
        r"(?i)(?<![A-Za-z0-9_])(?:sh|sz)?\d{6}",
        text,
    )
    if candidate:
        match = re.match(
            r"(?i)(?:sh|sz)?\d{6}(?:\.(?:sh|sz))?"
            r"(?![A-Za-z0-9_]|\.+(?=[^.\s]))",
            text[candidate.start():],
        )
        return normalize_symbol(match.group(0)) if match else ("UNKNOWN", "unknown")
    hk = re.search(
        r"(?i)(?<![A-Za-z0-9_])(\d{1,5}\.HK)(?![A-Za-z0-9_])",
        text,
    )
    if hk:
        return normalize_symbol(hk.group(1))
    for match in re.finditer(
        r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,4})?)"
        r"(?![A-Za-z0-9_])",
        text,
    ):
        candidate = match.group(1)
        if candidate not in _NON_TICKER:
            return normalize_symbol(candidate)
    return "UNKNOWN", "unknown"


@dataclass(frozen=True)
class ResearchRequest:
    symbol: str
    market: str
    question: str
    start_date: str
    end_date: str
    portfolio_value: float | None = None
    spread_bps: float | None = None

    @property
    def supported(self) -> bool:
        return self.market in {"cn", "hk", "us"}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ResearchRequest":
        topic = str(payload.get("topic") or payload.get("question") or "").strip()
        symbol, market = (
            normalize_symbol(str(payload["symbol"]))
            if payload.get("symbol")
            else symbol_from_text(topic)
        )
        today = date.today()
        end = str(
            payload.get("end_date")
            or _previous_weekday(today).strftime("%Y%m%d")
        )
        start = str(
            payload.get("start_date")
            or (today - timedelta(days=730)).strftime("%Y%m%d")
        )
        return cls(
            symbol=symbol,
            market=market,
            question=str(payload.get("question") or topic).strip(),
            start_date=start,
            end_date=end,
            portfolio_value=(
                float(payload["portfolio_value"])
                if payload.get("portfolio_value") is not None
                else None
            ),
            spread_bps=(
                float(payload["spread_bps"])
                if payload.get("spread_bps") is not None
                else None
            ),
        )
