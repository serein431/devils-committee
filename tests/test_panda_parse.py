"""DATA_MODE=panda landmine: real panda_data column names are unconfirmed
(TODO(feishu)) and the endpoint can return empty / error. These prove the parse
tolerates common column-name variants and degrades to mock instead of crashing
the live demo."""
import dataclasses
import sys
import types

from backend.config import CONFIG


class _Series(list):
    def tolist(self):
        return list(self)


class _FakeDF:
    """Minimal DataFrame-like: __contains__ + __getitem__(col)->series."""
    def __init__(self, cols: dict):
        self._c = {k: _Series(v) for k, v in cols.items()}
        self.columns = list(cols)

    def __contains__(self, k):
        return k in self._c

    def __getitem__(self, k):
        return self._c[k]


def _panda_mode(monkeypatch, tmp_path):
    from backend.skills import data, cache
    cfg = dataclasses.replace(CONFIG, data_mode="panda", cache_dir=str(tmp_path),
                              panda_username="u", panda_password="p",
                              panda_base_url="http://x")
    monkeypatch.setattr(data, "CONFIG", cfg)
    monkeypatch.setattr(cache, "CONFIG", cfg)
    return data


def _install_fake_panda(monkeypatch, df):
    mod = types.ModuleType("panda_data")
    mod.init_token = lambda **k: None
    mod.get_stock_daily = lambda **k: df
    monkeypatch.setitem(sys.modules, "panda_data", mod)


def test_parses_alternative_column_names(monkeypatch, tmp_path):
    data = _panda_mode(monkeypatch, tmp_path)
    df = _FakeDF({"trade_date": ["20240101", "20240102"],
                  "close_price": [10.0, 11.0], "vol": [100, 110]})
    _install_fake_panda(monkeypatch, df)
    bars = data.get_stock_daily("600519.SH")
    assert bars.source == "panda_live"
    assert bars.close == [10.0, 11.0] and bars.dates == ["20240101", "20240102"]


def test_newest_first_rows_are_sorted_chronologically(monkeypatch, tmp_path):
    """panda_data returns rows newest-first; parse must sort ascending so the
    return sign is correct (regression:茅台 fell but showed a gain when reversed)."""
    data = _panda_mode(monkeypatch, tmp_path)
    df = _FakeDF({"date": ["20241231", "20220104"],      # newest first, as panda returns
                  "close": [1524.0, 2051.0], "volume": [100, 200]})
    _install_fake_panda(monkeypatch, df)
    bars = data.get_stock_daily("600519.SH")
    assert bars.dates == ["20220104", "20241231"]        # ascending
    assert bars.close == [2051.0, 1524.0]
    assert bars.pct_change_total() < 0                    # a real decline reads negative


def test_volume_optional_falls_back(monkeypatch, tmp_path):
    data = _panda_mode(monkeypatch, tmp_path)
    df = _FakeDF({"date": ["20240101"], "close": [10.0]})   # no volume column
    _install_fake_panda(monkeypatch, df)
    bars = data.get_stock_daily("AAPL")
    assert bars.close == [10.0] and bars.volume == [10.0]


def test_empty_result_degrades_to_mock(monkeypatch, tmp_path):
    data = _panda_mode(monkeypatch, tmp_path)
    _install_fake_panda(monkeypatch, _FakeDF({"date": [], "close": []}))
    bars = data.get_stock_daily("TSLA")
    assert bars.source == "mock" and bars.n > 0      # demo still runs


def test_fetch_error_degrades_to_mock(monkeypatch, tmp_path):
    data = _panda_mode(monkeypatch, tmp_path)
    mod = types.ModuleType("panda_data")
    mod.init_token = lambda **k: None
    def boom(**k): raise RuntimeError("network down")
    mod.get_stock_daily = boom
    monkeypatch.setitem(sys.modules, "panda_data", mod)
    bars = data.get_stock_daily("NVDA")
    assert bars.source == "mock" and bars.n > 0
