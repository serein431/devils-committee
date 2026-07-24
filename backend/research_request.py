from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


def normalize_symbol(value: str) -> tuple[str, str]:
    raw = value.strip().upper()
    a_share = re.fullmatch(r"(?:(SH|SZ))?(\d{6})(?:\.(SH|SZ))?", raw)
    if a_share:
        prefix, digits, suffix = a_share.groups()
        exchange = suffix or prefix or ("SH" if digits.startswith("6") else "SZ")
        return f"{digits}.{exchange}", "cn"
    if re.fullmatch(r"\d{5}\.HK", raw) or re.fullmatch(r"[A-Z]{1,5}", raw):
        return raw, "unsupported"
    return "UNKNOWN", "unknown"


def symbol_from_text(text: str) -> tuple[str, str]:
    match = re.search(
        r"(?i)(?<!\w)(?:(?:sh|sz)\d{6}|\d{6}(?:\.(?:sh|sz))?)(?!\w)",
        text,
    )
    if match:
        return normalize_symbol(match.group(0))
    match = re.search(r"(?<!\w)(\d{5}\.HK|[A-Z]{1,5})(?!\w)", text)
    return normalize_symbol(match.group(1)) if match else ("UNKNOWN", "unknown")


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
        return self.market == "cn"

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ResearchRequest":
        topic = str(payload.get("topic") or payload.get("question") or "").strip()
        symbol, market = (
            normalize_symbol(str(payload["symbol"]))
            if payload.get("symbol")
            else symbol_from_text(topic)
        )
        end = str(payload.get("end_date") or date.today().strftime("%Y%m%d"))
        start = str(
            payload.get("start_date")
            or (date.today() - timedelta(days=730)).strftime("%Y%m%d")
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
