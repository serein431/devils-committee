"""Unit-test the REAL quant engine on controlled data (no network). Proves
cross-sectional IC, the long-short backtest, and — the differentiator — the
out-of-sample overfit rule are computed correctly, not seeded."""
import numpy as np

from backend.quant.panel import Panel
from backend.quant import research as R
from backend.quant import factors as F


def _panel(close: np.ndarray) -> Panel:
    T, N = close.shape
    syms = [f"S{i}" for i in range(N)]
    return Panel(dates=[f"d{t:04d}" for t in range(T)], symbols=syms,
                 close=close, names={s: s for s in syms})


def _trending(drift: np.ndarray, T: int, noise: float = 0.004) -> np.ndarray:
    """Persistent cross-sectional drift + small daily noise (so IC is high, not
    a degenerate exactly-1.0). Deterministic via a fixed LCG, no RNG globals."""
    close = np.ones((T, len(drift)))
    x = 12345
    for t in range(1, T):
        row = []
        for j in range(len(drift)):
            x = (1103515245 * x + 12345) & 0x7FFFFFFF
            row.append(close[t - 1, j] * (1 + drift[j] + ((x % 1000) / 1000 - 0.5) * noise))
        close[t] = row
    return close


def test_momentum_has_positive_ic_when_trends_persist():
    drift = np.linspace(-0.008, 0.008, 12)
    p = _panel(_trending(drift, 220))
    st = R.ICStats.of(R.ic_series(p, F.mom_20, fwd=5, lo=60, hi=p.T), fwd=5)
    assert st.mean > 0.3 and st.t_stat > 3           # strong, significant, but not degenerate


def test_backtest_returns_finite_and_positive_for_a_real_signal():
    drift = np.linspace(-0.008, 0.008, 12)
    p = _panel(_trending(drift, 220))
    bt = R.long_short(p, F.mom_20, fwd=5)
    assert np.isfinite(bt.sharpe) and bt.ann_return > 0
    assert bt.max_drawdown <= 0 and len(bt.equity) > 3


def test_overfit_rule_flags_in_sample_only_signal():
    """The core integrity check: strong IS + collapsed OOS -> overfit."""
    strong = R.ICStats(mean=0.05, ir=1.1, t_stat=3.0, hit=0.6, n=300)
    collapsed = R.ICStats(mean=-0.02, ir=-0.4, t_stat=-1.2, hit=0.47, n=200)
    of, reason = R.overfit_verdict(strong, collapsed)
    assert of and "样本外" in reason


def test_overfit_rule_passes_a_stable_signal():
    strong = R.ICStats(mean=0.05, ir=1.1, t_stat=3.0, hit=0.6, n=300)
    stable = R.ICStats(mean=0.045, ir=1.0, t_stat=2.6, hit=0.58, n=200)
    of, _ = R.overfit_verdict(strong, stable)
    assert not of


def test_thin_sample_is_flagged():
    thin = R.ICStats(mean=0.03, ir=0.4, t_stat=0.6, hit=0.5, n=12)
    of, reason = R.overfit_verdict(thin, thin)
    assert of and "样本" in reason


def test_ic_decay_returns_all_horizons():
    drift = np.linspace(-0.008, 0.008, 12)
    p = _panel(_trending(drift, 220))
    decay = R.ic_by_horizon(p, F.mom_20, horizons=(1, 5, 20))
    assert set(decay) == {1, 5, 20} and all(np.isfinite(v) for v in decay.values())


def test_composite_and_turnover_are_real():
    drift = np.linspace(-0.008, 0.008, 12)
    p = _panel(_trending(drift, 220))
    c = R.composite_result(p, ["mom_20", "low_vol"], fwd=5)
    assert np.isfinite(c["oos_ic"].mean)
    assert 0.0 <= c["backtest"].turnover <= 1.0        # turnover is a real fraction


def test_quantile_returns_are_monotonic_for_a_real_signal():
    drift = np.linspace(-0.008, 0.008, 15)
    p = _panel(_trending(drift, 240))
    q = R.quantile_returns(p, F.mom_20, fwd=5, n_q=5)
    assert len(q["bucket_returns"]) == 5
    assert q["monotonicity"] > 0.5 and q["top_minus_bottom"] > 0   # top beats bottom


def test_rolling_ic_returns_series_and_halves():
    drift = np.linspace(-0.008, 0.008, 12)
    p = _panel(_trending(drift, 240))
    r = R.rolling_ic(p, F.mom_20, fwd=5, window=10)
    assert isinstance(r["series"], list) and "first_half" in r and "second_half" in r


def test_factor_correlation_detects_redundancy():
    drift = np.linspace(-0.008, 0.008, 12)
    p = _panel(_trending(drift, 200))
    # mom_20 vs accel (=mom_20 - mom_60): related but not identical
    c = R.factor_correlation(p, ["mom_20", "accel"], fwd=5)
    assert "mom_20~accel" in c["pairs"] and 0 <= c["avg_abs_corr"] <= 1


def test_robust_keys_drops_overfit():
    good = R.FactorResult("a", "A", R.ICStats(0.05, 1, 3, .6, 300),
                          R.ICStats(0.04, 1, 2.5, .58, 200), R.Backtest(0, 1, 0), False, "")
    bad = R.FactorResult("b", "B", R.ICStats(0.06, 1, 3, .6, 300),
                         R.ICStats(-0.03, -1, -1.4, .45, 200), R.Backtest(0, 1, 0), True, "overfit")
    assert R.robust_keys([bad, good]) == ["a"]         # only the non-overfit survivor
