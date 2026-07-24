"""A small library of REAL factors, each computed from the price panel.

factor(panel, t) -> N-vector of factor values on date-row t (NaN where history
is insufficient). Every number here is derived from real prices — nothing seeded.
"""
from __future__ import annotations

import numpy as np

from .panel import Panel


def _ret_window(p: Panel, t: int, w: int) -> np.ndarray:
    if t - w < 0:
        return np.full(p.N, np.nan)
    return p.close[t] / p.close[t - w] - 1.0


def mom_20(p: Panel, t: int) -> np.ndarray:
    """20-day price momentum."""
    return _ret_window(p, t, 20)


def mom_60(p: Panel, t: int) -> np.ndarray:
    """60-day (quarterly) momentum."""
    return _ret_window(p, t, 60)


def rev_5(p: Panel, t: int) -> np.ndarray:
    """Short-term reversal: recent losers expected to bounce (negative 5d return)."""
    return -_ret_window(p, t, 5)


def accel(p: Panel, t: int) -> np.ndarray:
    """Momentum acceleration: 20d momentum minus 60d momentum."""
    return _ret_window(p, t, 20) - _ret_window(p, t, 60)


def low_vol(p: Panel, t: int, w: int = 20) -> np.ndarray:
    """Low-volatility factor: negative realized vol over a window."""
    if t - w < 1:
        return np.full(p.N, np.nan)
    seg = p.close[t - w:t + 1]
    r = seg[1:] / seg[:-1] - 1.0
    return -r.std(axis=0)


def dist_high(p: Panel, t: int, w: int = 60) -> np.ndarray:
    """Proximity to the 60-day high (a trend/breakout proxy)."""
    if t - w < 0:
        return np.full(p.N, np.nan)
    hi = p.close[t - w:t + 1].max(axis=0)
    return p.close[t] / hi - 1.0


REGISTRY = {
    "mom_20": ("20日动量", mom_20),
    "mom_60": ("60日动量", mom_60),
    "rev_5": ("5日反转", rev_5),
    "accel": ("动量加速", accel),
    "low_vol": ("低波动", low_vol),
    "dist_high": ("距60日高点", dist_high),
}
