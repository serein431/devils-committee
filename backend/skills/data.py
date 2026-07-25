"""panda_data wrapper with a local cache seam.

DATA_MODE=mock (default): deterministic synthetic daily bars so the whole engine
runs offline and reproducibly (no Date.now/random — seeded by the symbol).

DATA_MODE=panda: real panda_data==0.0.12. Matching requests use verified Parquet
cache files; cache misses call PandaData and never substitute synthetic bars.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from ..config import CONFIG
from ..research_request import ResearchRequest, normalize_symbol


class EvidenceUnavailable(RuntimeError):
    """Public error raised when verified market evidence cannot be read."""


@dataclass
class DailyBars:
    symbol: str
    dates: list[str]
    close: list[float]
    volume: list[float]
    source: str          # "mock" | "panda_cache" | "panda_live"

    @property
    def n(self) -> int:
        return len(self.close)

    def pct_change_total(self) -> float:
        if self.n < 2 or self.close[0] == 0:
            return 0.0
        return (self.close[-1] - self.close[0]) / self.close[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "n": self.n, "source": self.source,
            "first_date": self.dates[0] if self.dates else None,
            "last_date": self.dates[-1] if self.dates else None,
            "total_return": round(self.pct_change_total(), 4),
        }


def stable_seed(key: str) -> int:
    """Process-stable integer seed (unlike builtin hash(), which is randomized)."""
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)


def _seed(symbol: str) -> int:
    return stable_seed(symbol)


def _mock_bars(symbol: str, n: int = 250) -> DailyBars:
    """Deterministic pseudo-random walk seeded by the symbol (no RNG globals)."""
    s = _seed(symbol)
    price = 20.0 + (s % 480)            # 20..500 starting price
    dates, closes, vols = [], [], []
    x = s
    base_vol = 1_000_000 + (s % 9_000_000)
    for i in range(n):
        # LCG step — reproducible, no Math.random / Date.now
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        drift = ((x % 1000) / 1000.0 - 0.5) * 0.03      # +/-1.5% daily
        price = max(1.0, price * (1 + drift))
        y = (1103515245 * (x ^ i) + 12345) & 0x7FFFFFFF
        vol = base_vol * (0.6 + (y % 1000) / 1000.0)
        dates.append(f"2024{(i // 21) % 12 + 1:02d}{i % 21 + 1:02d}")
        closes.append(round(price, 2))
        vols.append(round(vol, 0))
    # For ~1/3 of symbols inject one deterministic unadjusted-corporate-action gap,
    # so the data-quality auditor has a REAL defect to find on those names.
    if stable_seed(symbol + "ca") % 3 == 0 and n > 40:
        gap_i = 30 + stable_seed(symbol + "gapidx") % (n - 40)
        closes[gap_i] = round(closes[gap_i - 1] * 0.70, 2)   # ~ -30% unadjusted split gap
    return DailyBars(symbol=symbol, dates=dates, close=closes, volume=vols, source="mock")


def get_stock_daily(symbol: str, start_date: str | None = None,
                    end_date: str | None = None) -> DailyBars:
    """Fetch daily bars. Mock by default; real panda_data when DATA_MODE=panda.

    Note: panda_data caps the date range at 5 years (error 100008); keep the
    default window under that."""
    if CONFIG.data_mode != "panda":
        return _mock_bars(symbol)

    from .panda import build_market_data_bundle

    normalized_symbol, market = normalize_symbol(symbol)
    defaults = ResearchRequest.from_payload({"symbol": normalized_symbol})
    request = ResearchRequest(
        symbol=normalized_symbol,
        market=market,
        question="daily market data",
        start_date=start_date or defaults.start_date,
        end_date=end_date or defaults.end_date,
    )
    bundle = build_market_data_bundle(request)
    if bundle.status != "success" or "daily" not in bundle.datasets:
        warning = bundle.warnings[-1] if bundle.warnings else "daily dataset unavailable"
        raise EvidenceUnavailable(warning)

    artifact = bundle.datasets["daily"]
    try:
        import pandas as pd  # type: ignore

        frame = pd.read_parquet(artifact.path)
        dates, close, volume = _parse_panda_df(frame)
    except EvidenceUnavailable:
        raise
    except Exception:
        raise EvidenceUnavailable("daily dataset unreadable") from None
    if not close:
        raise EvidenceUnavailable("daily dataset unavailable")
    source = "panda_live" if artifact.mode == "live" else "panda_cache"
    return DailyBars(
        symbol=normalized_symbol,
        dates=dates,
        close=close,
        volume=volume,
        source=source,
    )


def _col(df, names: list[str]):
    """Resolve the first present column from supported PandaData aliases."""
    for n in names:
        try:
            if n in getattr(df, "columns", []) or (hasattr(df, "__contains__") and n in df):
                return df[n].tolist()
        except Exception:
            continue
    raise KeyError(f"none of columns {names} present")


def _parse_panda_df(df):
    """Flexible parse: tolerate common column-name variants for date/close/volume.

    panda_data returns rows newest-first; we sort ASCENDING by date so total_return
    and jump-detection have the correct chronological order (else the return sign
    flips)."""
    dates = [str(d) for d in _col(df, ["date", "trade_date", "datetime", "day"])]
    close = [float(c) for c in _col(df, ["close", "close_price", "adj_close", "closePrice"])]
    try:
        vol = [float(v) for v in _col(df, ["volume", "vol", "qty", "turnover_volume"])]
    except KeyError:
        raise EvidenceUnavailable("daily volume unavailable") from None
    rows = sorted(zip(dates, close, vol), key=lambda r: r[0])   # oldest -> newest
    if not rows:
        return [], [], []
    d, c, v = zip(*rows)
    return list(d), list(c), list(v)
