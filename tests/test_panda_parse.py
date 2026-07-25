import dataclasses
import builtins
import json
import sys
import types
from datetime import date, datetime
from pathlib import Path

import pytest

from backend.config import CONFIG
from backend.research_request import ResearchRequest


class _Series(list):
    def tolist(self):
        return list(self)

    def map(self, function):
        return _Series(function(value) for value in self)


class _FakeFrame:
    """Small pandas-like frame used without pandas or pyarrow."""

    def __init__(self, rows):
        self.rows = [dict(row) for row in rows]
        self.columns = list(rows[0]) if rows else []

    def __len__(self):
        return len(self.rows)

    @property
    def empty(self):
        return not self.rows

    def copy(self):
        return _FakeFrame(self.rows)

    def rename(self, columns):
        self.rows = [
            {columns.get(key, key): value for key, value in row.items()}
            for row in self.rows
        ]
        self.columns = [columns.get(column, column) for column in self.columns]
        return self

    def __contains__(self, key):
        return key in self.columns

    def __getitem__(self, key):
        return _Series(row.get(key) for row in self.rows)

    def __setitem__(self, key, values):
        for row, value in zip(self.rows, values):
            row[key] = value
        if key not in self.columns:
            self.columns.append(key)

    def sort_values(self, by):
        self.rows.sort(key=lambda row: tuple(row.get(key, "") for key in by))
        return self

    def drop_duplicates(self):
        unique = []
        seen = set()
        for row in self.rows:
            marker = tuple((column, row.get(column)) for column in self.columns)
            if marker not in seen:
                seen.add(marker)
                unique.append(row)
        self.rows = unique
        return self

    def reset_index(self, drop=False):
        assert drop is True
        return self

    def to_parquet(self, path, index=False):
        assert index is False
        payload = json.dumps(
            self.rows,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        Path(path).write_bytes(payload)


def _request(symbol="600519.SH", market="cn"):
    return ResearchRequest(
        symbol=symbol,
        market=market,
        question="测试行情证据",
        start_date="20240101",
        end_date="20240131",
    )


def _panda_mode(monkeypatch, tmp_path):
    from backend.skills import data, panda

    cfg = dataclasses.replace(
        CONFIG,
        data_mode="panda",
        cache_dir=str(tmp_path),
        panda_username="user",
        panda_password="private-password",
        panda_base_url="https://panda.invalid",
    )
    monkeypatch.setattr(panda, "CONFIG", cfg)
    monkeypatch.setattr(data, "CONFIG", cfg)
    return panda, data


def _install_fake_panda(monkeypatch, daily=None, daily_error=None):
    module = types.ModuleType("panda_data")
    module.__version__ = "0.0.12"
    module.init_token = lambda **kwargs: None

    def get_daily(**kwargs):
        if daily_error is not None:
            raise daily_error
        return daily

    module.get_stock_daily = get_daily
    for method in (
        "get_stock_daily_pre",
        "get_stock_daily_post",
        "get_adj_factor",
        "get_stock_dividend",
        "get_stock_status_change",
        "get_trade_list",
        "get_index_weights",
        "get_index_daily",
        "get_factor",
    ):
        setattr(module, method, lambda **kwargs: _FakeFrame([]))
    monkeypatch.setitem(sys.modules, "panda_data", module)
    return module


def test_empty_live_daily_is_insufficient_and_never_mock(monkeypatch, tmp_path):
    panda, _ = _panda_mode(monkeypatch, tmp_path)
    _install_fake_panda(monkeypatch, daily=_FakeFrame([]))

    bundle = panda.build_market_data_bundle(_request())

    assert bundle.status == "insufficient-evidence"
    assert bundle.mode != "mock"
    assert "daily" not in bundle.datasets
    assert bundle.datasets["status_change"].rows == 0


def test_empty_status_change_is_kept_as_valid_empty_evidence(monkeypatch, tmp_path):
    panda, _ = _panda_mode(monkeypatch, tmp_path)
    _install_fake_panda(
        monkeypatch,
        daily=_FakeFrame([
            {
                "date": "20240102",
                "symbol": "600519.SH",
                "close": 10.0,
                "volume": 100,
            }
        ]),
    )

    bundle = panda.build_market_data_bundle(_request())

    assert bundle.status == "success"
    assert bundle.datasets["status_change"].rows == 0
    assert "status_change returned no rows" not in bundle.warnings


def test_live_request_error_is_public_and_never_mock(monkeypatch, tmp_path):
    panda, _ = _panda_mode(monkeypatch, tmp_path)
    _install_fake_panda(
        monkeypatch,
        daily_error=RuntimeError("private upstream response and token detail"),
    )

    bundle = panda.build_market_data_bundle(_request())
    public_result = json.dumps(bundle.to_dict(), ensure_ascii=False)

    assert bundle.status == "insufficient-evidence"
    assert bundle.mode != "mock"
    assert "RuntimeError" not in public_result
    assert "private upstream response" not in public_result
    assert "token detail" not in public_result


def test_cached_daily_survives_authentication_failure(monkeypatch, tmp_path):
    from backend.skills.cache import DatasetCache

    panda, _ = _panda_mode(monkeypatch, tmp_path)
    request = _request()
    method, params_factory = panda.DATASET_CALLS["daily"]
    cache = DatasetCache(tmp_path, CONFIG.data_version)
    cache.save(
        "daily",
        method,
        params_factory(request),
        "0.0.12",
        _FakeFrame([
            {"date": "20240101", "symbol": "600519.SH", "close": 10.0, "volume": 100},
        ]),
    )
    module = _install_fake_panda(monkeypatch, daily_error=AssertionError("must not fetch"))
    service_calls = []

    def reject_service_call(method_name):
        def reject(**kwargs):
            service_calls.append(method_name)
            raise AssertionError("service method called after authentication failure")

        return reject

    for method_name, _ in panda.DATASET_CALLS.values():
        setattr(module, method_name, reject_service_call(method_name))
    module.init_token = lambda **kwargs: (_ for _ in ()).throw(
        RuntimeError("private authentication response")
    )

    bundle = panda.build_market_data_bundle(request)
    public_result = json.dumps(bundle.to_dict(), ensure_ascii=False)

    assert bundle.status == "success"
    assert bundle.mode == "cache"
    assert bundle.datasets["daily"].mode == "cache"
    assert "PandaData authentication unavailable" in bundle.warnings
    assert service_calls == []
    assert "RuntimeError" not in public_result
    assert "private authentication response" not in public_result


def test_cached_daily_is_used_when_panda_module_import_fails(monkeypatch, tmp_path):
    from backend.skills.cache import DatasetCache

    panda, _ = _panda_mode(monkeypatch, tmp_path)
    request = _request()
    method, params_factory = panda.DATASET_CALLS["daily"]
    DatasetCache(tmp_path, CONFIG.data_version).save(
        "daily",
        method,
        params_factory(request),
        "0.0.12",
        _FakeFrame([
            {"date": "20240101", "symbol": "600519.SH", "close": 10.0, "volume": 100},
        ]),
    )
    original_import = builtins.__import__

    def reject_panda_import(name, *args, **kwargs):
        if name == "panda_data":
            raise ImportError("private import detail")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_panda_import)
    monkeypatch.delitem(sys.modules, "panda_data", raising=False)

    bundle = panda.build_market_data_bundle(request)

    assert bundle.status == "success"
    assert bundle.mode == "cache"
    assert bundle.datasets["daily"].mode == "cache"
    assert "PandaData authentication unavailable" in bundle.warnings
    assert "private import detail" not in " ".join(bundle.warnings)


def test_normalize_frame_cleans_dates_sorts_and_deduplicates():
    from backend.skills.panda import normalize_frame

    frame = _FakeFrame([
        {" date ": "2024-01-03", "symbol": "600519.SH", "close": 11.0},
        {" date ": "20240102.0", "symbol": "600519.SH", "close": 10.0},
        {" date ": "20240102.0", "symbol": "600519.SH", "close": 10.0},
        {" date ": None, "symbol": "600519.SH", "close": 9.0},
    ])

    normalized = normalize_frame(frame)

    assert [row["date"] for row in normalized.rows] == ["", "20240102", "20240103"]
    assert all(len(row["date"]) == 8 for row in normalized.rows if row["date"])
    assert len(normalized) == 3


def test_normalize_frame_handles_real_pandas_date_scalars():
    pd = pytest.importorskip("pandas")
    np = pytest.importorskip("numpy")
    from backend.skills.panda import normalize_frame

    frame = pd.DataFrame({
        "date": [
            pd.Timestamp("2024-01-01 12:30:00"),
            datetime(2024, 1, 2, 9, 15),
            date(2024, 1, 3),
            np.datetime64("2024-01-04"),
            pd.NaT,
            pd.NA,
            np.nan,
            20240105,
            20240106.0,
            "20240107",
            "2024-01-08",
            "2024-01-09 23:59:59",
        ],
        "symbol": ["600519.SH"] * 12,
        "row_id": list(range(12)),
    })

    normalized = normalize_frame(frame)
    values = normalized["date"].tolist()

    assert values == [
        "",
        "",
        "",
        "20240101",
        "20240102",
        "20240103",
        "20240104",
        "20240105",
        "20240106",
        "20240107",
        "20240108",
        "20240109",
    ]
    assert all(value == "" or (len(value) == 8 and value.isdigit()) for value in values)


@pytest.mark.parametrize("value", ["not-a-date", "2024-01-01 garbage"])
def test_normalize_frame_rejects_unparseable_real_pandas_date(value):
    pd = pytest.importorskip("pandas")
    from backend.skills.panda import normalize_frame

    with pytest.raises(ValueError, match="invalid date value"):
        normalize_frame(pd.DataFrame({"date": [value]}))


@pytest.mark.parametrize(
    "column",
    ["Authorization", "access_TOKEN", "dbPassword", "client_secret", "CookieJar"],
)
def test_normalize_frame_rejects_sensitive_columns(column):
    from backend.skills.panda import normalize_frame

    with pytest.raises(ValueError):
        normalize_frame(_FakeFrame([{"date": "20240101", column: "sensitive"}]))


def test_live_daily_is_cached_with_exact_request_parameters(monkeypatch, tmp_path):
    panda, _ = _panda_mode(monkeypatch, tmp_path)
    module = _install_fake_panda(
        monkeypatch,
        daily=_FakeFrame([
            {"date": "2024-01-02", "symbol": "600519.SH", "close": 11.0, "volume": 110},
            {"date": "2024-01-01", "symbol": "600519.SH", "close": 10.0, "volume": 100},
        ]),
    )
    calls = []
    original = module.get_stock_daily
    module.get_stock_daily = lambda **kwargs: (calls.append(kwargs), original(**kwargs))[1]

    bundle = panda.build_market_data_bundle(_request())

    assert bundle.status == "success"
    assert bundle.mode == "live"
    assert bundle.datasets["daily"].rows == 2
    assert calls == [{
        "symbol": ["600519.SH"],
        "start_date": "20240101",
        "end_date": "20240131",
        "fields": [],
        "indicator": "000300",
        "st": True,
    }]


def test_data_layer_raises_public_error_when_daily_is_insufficient(monkeypatch, tmp_path):
    _, data = _panda_mode(monkeypatch, tmp_path)
    _install_fake_panda(monkeypatch, daily=_FakeFrame([]))

    with pytest.raises(data.EvidenceUnavailable, match="daily dataset unavailable"):
        data.get_stock_daily("600519.SH", "20240101", "20240131")


def test_data_layer_rejects_real_daily_without_volume(monkeypatch, tmp_path):
    from backend.skills.contracts import DatasetArtifact, MarketDataBundle

    panda, data = _panda_mode(monkeypatch, tmp_path)
    artifact = DatasetArtifact(
        name="daily",
        method="get_stock_daily",
        params={},
        path=str(tmp_path / "daily.parquet"),
        sha256="abc",
        rows=1,
        mode="cache",
        fetched_at="2026-07-24T00:00:00+00:00",
    )
    bundle = MarketDataBundle(
        "600519.SH",
        "success",
        "cache",
        {"daily": artifact},
    )
    monkeypatch.setattr(panda, "build_market_data_bundle", lambda request: bundle)
    pandas_module = types.ModuleType("pandas")
    pandas_module.read_parquet = lambda path: _FakeFrame([
        {"date": "20240101", "close": 10.0},
    ])
    monkeypatch.setitem(sys.modules, "pandas", pandas_module)

    with pytest.raises(data.EvidenceUnavailable, match="daily volume unavailable"):
        data.get_stock_daily("600519.SH", "20240101", "20240131")


def test_existing_parser_handles_alternative_names_and_sorting():
    from backend.skills.data import _parse_panda_df

    frame = _FakeFrame([
        {"trade_date": "20240102", "close_price": 11.0, "vol": 110},
        {"trade_date": "20240101", "close_price": 10.0, "vol": 100},
    ])

    dates, close, volume = _parse_panda_df(frame)

    assert dates == ["20240101", "20240102"]
    assert close == [10.0, 11.0]
    assert volume == [100.0, 110.0]


def test_mock_mode_keeps_deterministic_mock_behavior(monkeypatch, tmp_path):
    from backend.skills import data

    monkeypatch.setattr(
        data,
        "CONFIG",
        dataclasses.replace(CONFIG, cache_dir=str(tmp_path), data_mode="mock"),
    )

    first = data.get_stock_daily("600519.SH")
    second = data.get_stock_daily("600519.SH")

    assert first.source == "mock"
    assert first.close == second.close
