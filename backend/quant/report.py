"""Cached real-research provider the debate consumes (DATA_MODE=panda only).

research(): evaluate the whole factor library on the real panel, once per process.
factor_evidence(symbol): the top factors + THIS symbol's real rank on each, plus the
real overfit verdict — so the bull argues real signals and the audit catches a real
overfit, not a seeded one.
"""
from __future__ import annotations

import numpy as np

from . import factors as F
from .panel import load_panel
from .research import rank_factors

_CACHE: dict = {}


def research(fwd: int = 5):
    if "res" not in _CACHE:
        p = load_panel()
        _CACHE["panel"] = p
        _CACHE["res"] = rank_factors(p, fwd)
        _CACHE["fwd"] = fwd
    return _CACHE["panel"], _CACHE["res"]


def factor_evidence(symbol: str, fwd: int = 5) -> dict:
    """Real factor evidence for the debate. Top factors by in-sample IC (as a naive
    picker would rank them) + this symbol's cross-sectional rank + overfit verdict."""
    p, res = research(fwd)
    t = p.T - 1
    j = p.symbols.index(symbol) if symbol in p.symbols else None
    ranked = []
    for r in res[:3]:
        fn = F.REGISTRY[r.key][1]
        vals = fn(p, t)
        rank = None
        if j is not None and np.isfinite(vals[j]):
            fin = vals[np.isfinite(vals)]
            rank = round(float((fin < vals[j]).mean()), 2)
        ranked.append({
            "name": r.key, "label": r.label,
            "ic": r.is_ic.mean, "ir": r.is_ic.ir, "t": r.is_ic.t_stat, "n_obs": r.is_ic.n,
            "oos_ic": r.oos_ic.mean, "oos_t": r.oos_ic.t_stat,
            "overfit": r.overfit, "overfit_reason": r.overfit_reason,
            "sharpe": r.backtest.sharpe, "ann_return": r.backtest.ann_return,
            "max_drawdown": r.backtest.max_drawdown,
            "in_universe": j is not None, "rank_pct": rank,
        })
    return {"symbol": symbol, "in_universe": j is not None,
            "universe_n": p.N, "window": f"{p.dates[0]}..{p.dates[-1]}",
            "ranked_factors": ranked}


def full_report(fwd: int = 5) -> dict:
    """Serializable factor-research report (for /research + the deck/whitepaper)."""
    from .research import (ic_by_horizon, composite_result, robust_keys,
                           quantile_returns, rolling_ic, factor_correlation)
    from . import factors as F
    p, res = research(fwd)
    keys = robust_keys(res)
    comp = composite_result(p, keys, fwd)
    naive = res[0]                       # best in-sample IC = what a naive picker takes
    all_keys = [r.key for r in res]
    return {
        "universe_n": p.N, "n_bars": p.T, "fwd": fwd,
        "window": f"{p.dates[0]}..{p.dates[-1]}",
        "factors": [{
            "key": r.key, "label": r.label,
            "is_ic": r.is_ic.mean, "is_t": r.is_ic.t_stat, "is_n": r.is_ic.n,
            "oos_ic": r.oos_ic.mean, "oos_t": r.oos_ic.t_stat,
            "ann_return": r.backtest.ann_return, "sharpe": r.backtest.sharpe,
            "max_drawdown": r.backtest.max_drawdown, "turnover": r.backtest.turnover,
            "equity": r.backtest.equity,
            "ic_decay": ic_by_horizon(p, F.REGISTRY[r.key][1]),
            "quantiles": quantile_returns(p, F.REGISTRY[r.key][1], fwd),
            "overfit": r.overfit, "overfit_reason": r.overfit_reason,
        } for r in res],
        "rolling_ic_overfit": {"factor": naive.key,
                               **rolling_ic(p, F.REGISTRY[naive.key][1], fwd)},
        "correlation": factor_correlation(p, all_keys, fwd),
        # the audit's payoff: drop overfit, combine the survivors
        "audit_improves": {
            "naive_pick": naive.key, "naive_overfit": naive.overfit,
            "naive_oos_ic": naive.oos_ic.mean, "naive_sharpe": naive.backtest.sharpe,
            "robust_keys": keys,
            "composite_oos_ic": comp["oos_ic"].mean, "composite_oos_t": comp["oos_ic"].t_stat,
            "composite_sharpe": comp["backtest"].sharpe,
            "composite_ann": comp["backtest"].ann_return,
            "composite_mdd": comp["backtest"].max_drawdown,
            "composite_turnover": comp["backtest"].turnover,
            "composite_equity": comp["backtest"].equity,
        },
    }

