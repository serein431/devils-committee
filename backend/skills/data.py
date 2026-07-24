"""panda_data wrapper with a local cache seam.

DATA_MODE=mock (default): deterministic synthetic daily bars so the whole engine
runs offline and reproducibly (no Date.now/random — seeded by the symbol).

DATA_MODE=panda: real panda_data==0.0.12. Per the plan's 7-day data window, we
pull once into a DuckDB/Parquet cache and read the cache during judging so a
window expiry or rate-limit can't break the live demo.

TODO(feishu): confirm exact panda_data auth + method signatures from the group.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from ..config import CONFIG


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


def get_universe_rows(symbol: str) -> tuple[list[dict], str]:
    """Point-in-time universe rows for the survivorship auditor (SKILL_MODE=cli).

    Schema required by skill-survivorship-universe-auditor:
      symbol,date,listed_at,delisted_at,return,delisting_return,eligible,stable_id

    DATA_MODE=panda: real membership (TODO(feishu): via get_stock_status_change).
    DATA_MODE=mock: a small SYNTHETIC universe around the symbol — clearly labeled
    'mock-synthetic' so a real audit is never mistaken for a real-universe audit.
    It includes a delisted peer with a missing delisting return, so the REAL
    auditor honestly reports a survivorship problem to demonstrate the wiring.
    """
    if CONFIG.data_mode == "panda":
        raise NotImplementedError("TODO(feishu): build real universe via panda_data")
    d = "2024-06-28"
    rows = [
        {"symbol": symbol, "date": d, "listed_at": "2001-08-27", "delisted_at": "",
         "return": "0.012", "delisting_return": "", "eligible": "1", "stable_id": symbol},
    ]
    # ~half of symbols carry a delisted peer with missing delisting returns, so the
    # REAL auditor flags survivorship on those and PASSES the rest — the synthetic
    # universe discriminates instead of always failing. (Real universe via panda.)
    if stable_seed(symbol + "surv") % 2 == 0:
        peer = f"DL{stable_seed(symbol) % 900 + 100}.SH"
        rows.append({"symbol": peer, "date": d, "listed_at": "2010-01-01",
                     "delisted_at": d, "return": "", "delisting_return": "",
                     "eligible": "1", "stable_id": peer})
    else:
        good = f"GD{stable_seed(symbol) % 900 + 100}.SH"
        rows.append({"symbol": good, "date": d, "listed_at": "2015-01-01",
                     "delisted_at": "", "return": "0.006", "delisting_return": "",
                     "eligible": "1", "stable_id": good})
    return rows, "mock-synthetic"


def get_adjustment_rows(symbol: str) -> tuple[list[dict], str]:
    """Rows for skill-corporate-action-adjustment-auditor (SKILL_MODE=cli).

    Schema: symbol,date,close,adj_close,split_factor,cash_dividend.
    Built from the (mock or real) daily bars. adj_close mirrors close with no
    split/dividend recorded — so any large raw jump (e.g. the injected ~-15%
    unadjusted gap) is genuinely unexplained and the REAL auditor flags it.
    Labeled 'mock-synthetic' in mock mode; never passed off as a real CA ledger.
    """
    b = get_stock_daily(symbol)
    src = "panda" if CONFIG.data_mode == "panda" else "mock-synthetic"
    rows = [{"symbol": symbol,
             "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}",
             "close": c, "adj_close": c, "split_factor": 1, "cash_dividend": 0}
            for d, c in zip(b.dates, b.close)]
    return rows, src


def get_stock_daily(symbol: str, start_date: str = "20220101",
                    end_date: str = "20241231") -> DailyBars:
    """Fetch daily bars. Mock by default; real panda_data when DATA_MODE=panda.

    Note: panda_data caps the date range at 5 years (error 100008); keep the
    default window under that."""
    if CONFIG.data_mode != "panda":
        return _mock_bars(symbol)

    # --- real path (needs Feishu creds) ------------------------------------
    # Cache-first: pull ONCE inside the 7-day window, serve from cache at judging
    # so a window expiry / rate-limit can't break the live demo (service_checklist).
    from . import cache
    cached = cache.load(symbol)
    if cached:
        return DailyBars(symbol=symbol, dates=cached["dates"], close=cached["close"],
                         volume=cached["volume"], source="panda_cache")

    try:
        import panda_data  # type: ignore
        panda_data.init_token(
            username=CONFIG.panda_username,
            password=CONFIG.panda_password,
            base_url=CONFIG.panda_base_url,
        )
        df = panda_data.get_stock_daily(
            symbol=[symbol], start_date=start_date, end_date=end_date,
            fields=[], indicator="000300", st=True,
        )
        dates, close, vol = _parse_panda_df(df)
        if not close:
            raise ValueError("empty result from panda_data")
        cache.save(symbol, {"dates": dates, "close": close, "volume": vol})
        return DailyBars(symbol=symbol, dates=dates, close=close,
                         volume=vol, source="panda_live")
    except Exception as e:
        # Never crash the live demo on a data hiccup — degrade to deterministic mock.
        logging.getLogger("devils-committee").warning(
            "panda_data fetch failed for %s (%s); using mock bars", symbol, str(e)[:120])
        return _mock_bars(symbol)


def _col(df, names: list[str]):
    """Resolve the first present column (exact panda_data names TODO(feishu))."""
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
        vol = [float(v) for v in _col(df, ["volume", "vol", "turnover_volume", "amount"])]
    except KeyError:
        vol = list(close)                     # volume optional; fall back to a stand-in
    rows = sorted(zip(dates, close, vol), key=lambda r: r[0])   # oldest -> newest
    if not rows:
        return [], [], []
    d, c, v = zip(*rows)
    return list(d), list(c), list(v)
