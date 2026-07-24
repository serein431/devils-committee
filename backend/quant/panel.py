"""Build an aligned price/return panel from REAL panda_data across a universe.

A Panel is dates (T) × symbols (N) matrices of close and forward returns —
the substrate every real factor and backtest computes on.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..skills.data import get_stock_daily

# A fixed, liquid A-share universe (index heavyweights across sectors). Real data
# for all of these is fetched from panda_data and cached.
DEFAULT_UNIVERSE = [
    "600519.SH", "601318.SH", "000001.SZ", "600036.SH", "000858.SZ", "300750.SZ",
    "002594.SZ", "600030.SH", "000651.SZ", "601899.SH", "600900.SH", "000333.SZ",
    "601166.SH", "600276.SH", "000725.SZ", "002415.SZ", "600887.SH", "601288.SH",
    "000002.SZ", "600028.SH", "600809.SH", "300059.SZ", "002304.SZ", "601088.SH",
]


@dataclass
class Panel:
    dates: list[str]          # length T (ascending)
    symbols: list[str]        # length N
    close: np.ndarray         # T × N
    names: dict[str, str]     # symbol -> display name (best-effort)

    @property
    def T(self) -> int:
        return self.close.shape[0]

    @property
    def N(self) -> int:
        return self.close.shape[1]

    def returns(self) -> np.ndarray:
        """Simple daily returns, (T-1) × N."""
        return self.close[1:] / self.close[:-1] - 1.0

    def fwd_return(self, t: int, horizon: int) -> np.ndarray:
        """N-vector of forward `horizon`-day returns starting at row t."""
        return self.close[t + horizon] / self.close[t] - 1.0


def load_panel(symbols: list[str] | None = None, min_bars: int = 250) -> Panel:
    """Fetch each symbol's real bars, align to the common trading calendar."""
    symbols = symbols or DEFAULT_UNIVERSE
    series: dict[str, dict] = {}
    for s in symbols:
        try:
            b = get_stock_daily(s)
        except Exception:
            continue
        if b.n >= min_bars:
            series[s] = {"idx": {d: i for i, d in enumerate(b.dates)},
                         "close": np.asarray(b.close, dtype=float),
                         "dates": b.dates}
    if not series:
        raise RuntimeError("no symbols loaded for panel")
    common = None
    for s in series:
        ds = set(series[s]["dates"])
        common = ds if common is None else (common & ds)
    dates = sorted(common)
    syms = list(series)
    close = np.array([[series[s]["close"][series[s]["idx"][d]] for s in syms]
                      for d in dates], dtype=float)
    return Panel(dates=dates, symbols=syms, close=close, names={s: s for s in syms})
