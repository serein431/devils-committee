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
    from backend.skills.panda import DATASET_CALLS

    module = types.ModuleType("panda_data")
    module.__version__ = "0.0.12"
    module.init_token = lambda **kwargs: None

    def get_daily(**kwargs):
        if daily_error is not None:
            raise daily_error
        return daily

    module.get_stock_daily = get_daily
    for method in {item[0] for item in DATASET_CALLS.values()}:
        if method != "get_stock_daily":
            setattr(module, method, lambda **kwargs: _FakeFrame([]))
    module.get_trade_cal = lambda **kwargs: _FakeFrame([])
    monkeypatch.setitem(sys.modules, "panda_data", module)
    return module


def test_sz_symbol_uses_documented_a_share_trade_list_selector():
    from backend.skills.panda import DATASET_CALLS

    request = _request(symbol="300750.SZ")

    start_method, start_params = DATASET_CALLS["trade_list_start"]
    end_method, end_params = DATASET_CALLS["trade_list_end"]

    assert start_method == end_method == "get_trade_list"
    assert start_params(request) == {"date": "20240101", "exchange": "SH"}
    assert end_params(request) == {"date": "20240131", "exchange": "SH"}


def test_company_research_uses_documented_panda_endpoints():
    from backend.skills.panda import DATASET_CALLS

    request = _request(symbol="601628.SH")
    industry_method, industry_params = DATASET_CALLS["industry"]
    finance_method, finance_params = DATASET_CALLS["financial_performance"]
    reports_method, reports_params = DATASET_CALLS["financial_reports"]

    assert industry_method == "get_stock_industry"
    assert industry_params(request) == {
        "stock_symbol": "601628.SH",
        "level": "L1",
    }
    assert finance_method == "get_fina_performance"
    params = finance_params(request)
    assert params["symbol"] == "601628.SH"
    assert "operating_revenue_yoy" in params["fields"]
    assert "net_profit_parent_yoy" in params["fields"]
    assert "net_cash_flow_operating" in params["fields"]
    assert reports_method == "get_fina_reports"
    assert reports_params(request) == {
        "symbol": "601628.SH",
        "start_quarter": "2023q1",
        "end_quarter": "2024q1",
        "date": "20240131",
        "is_latest": True,
        "fields": [],
    }


def test_extended_research_registry_uses_high_value_panda_endpoints():
    from backend.skills.panda import DATASET_CALLS

    expected = {
        "financial_forecast": "get_fina_forecast",
        "audit_opinion": "get_audit_opinion",
        "industry_detail": "get_industry_detail",
        "index_indicator": "get_index_indicator",
        "margin": "get_margin",
        "northbound_holding": "get_hsgt_hold",
        "holder_count": "get_holder_count",
        "top_holders": "get_top_holders",
        "stock_pledge": "get_stock_pledge",
        "shareholder_change": "get_stock_shareholder_change",
        "repurchase": "get_repurchase",
        "restricted_release": "get_restricted_list",
        "litigation": "get_stock_litigation_arbitration",
        "material_contract": "get_stock_material_contract",
        "macro_ir": "get_macro_ir",
        "macro_mb": "get_macro_mb",
    }

    assert {name: DATASET_CALLS[name][0] for name in expected} == expected


def test_foreign_market_registry_routes_complete_hk_and_us_research_sets():
    from backend.skills.panda import FOREIGN_DATASET_CALLS, _selected_dataset_names

    expected_names = {
        "daily",
        "stock_detail",
        "financial_reports",
        "operating_metrics",
        "market_financial",
        "industry_median",
        "price_volume",
        "recommendation_consensus",
        "noncyclical_consensus",
        "investor_concentration",
        "top20_concentration",
        "investor_ranking",
        "insider_transactions",
        "shareholder_holdings",
        "dividend_events",
        "market_events",
        "meeting_events",
        "financial_events",
        "ir_events",
    }
    hk = ResearchRequest("0700.HK", "hk", "分析腾讯", "20240101", "20260724")
    us = ResearchRequest("AAPL", "us", "分析苹果", "20240101", "20260724")

    assert _selected_dataset_names(hk) == expected_names
    assert _selected_dataset_names(us) == expected_names
    assert FOREIGN_DATASET_CALLS["hk"]["daily"][0] == "get_hk_daily"
    assert FOREIGN_DATASET_CALLS["hk"]["financial_reports"][0] == "get_fina_statement"
    assert FOREIGN_DATASET_CALLS["us"]["daily"][0] == "get_us_daily"
    assert FOREIGN_DATASET_CALLS["us"]["financial_reports"][0] == "get_fina_ex"


def test_sector_macro_router_covers_battery_and_food_industries():
    from backend.skills.panda import MACRO_SECTOR_BY_INDUSTRY

    assert MACRO_SECTOR_BY_INDUSTRY["电力设备"] == (
        "get_macro_ep",
        ["EP0000399", "EP0000400"],
    )
    assert MACRO_SECTOR_BY_INDUSTRY["食品饮料"] == (
        "get_macro_fb",
        ["FB0045844", "FB0045846"],
    )


def test_dynamic_router_only_adds_intraday_and_management_calls_when_requested():
    from backend.skills.panda import _selected_dataset_names

    ordinary = _selected_dataset_names(_request())
    intraday = _selected_dataset_names(
        ResearchRequest(
            "600519.SH",
            "cn",
            "看一下盘中实时走势和管理层调研",
            "20240101",
            "20240131",
        )
    )

    assert "stock_rt_minute" not in ordinary
    assert "investor_brief" not in ordinary
    assert {"stock_rt_daily", "stock_minute", "stock_rt_minute", "index_minute"} <= intraday
    assert "investor_brief" in intraday


def test_trading_date_resolver_uses_real_calendar_boundaries(monkeypatch, tmp_path):
    panda, _ = _panda_mode(monkeypatch, tmp_path)
    module = _install_fake_panda(monkeypatch, daily=_FakeFrame([]))
    module.get_trade_cal = lambda **kwargs: _FakeFrame(
        [
            {"nature_date": "20240102"},
            {"nature_date": "20240103"},
            {"nature_date": "20240105"},
        ]
    )

    resolved = panda.resolve_request_trading_dates(_request())

    assert resolved.start_date == "20240102"
    assert resolved.end_date == "20240105"


def test_normalize_frame_converts_string_nan_before_parquet_serialization():
    from backend.skills.panda import normalize_frame

    frame = _FakeFrame(
        [
            {"date": "2024-01-02", "ratio": 1.2},
            {"date": "2024-01-03", "ratio": "NaN"},
        ]
    )

    normalized = normalize_frame(frame)

    assert normalized.rows == [
        {"date": "20240102", "ratio": 1.2},
        {"date": "20240103", "ratio": None},
    ]


def test_peer_factor_router_always_keeps_target_with_large_industry(monkeypatch):
    from backend.skills import panda

    peers = [
        {"stock_symbol": f"{index:06d}.SZ"}
        for index in range(100)
    ]
    monkeypatch.setattr(panda, "_artifact_records", lambda artifact: peers)

    calls = panda._peer_factor_call(
        _request(symbol="601628.SH"),
        {"industry_peers": object()},
    )

    symbols = calls["industry_peer_factors"][1]["symbol"]
    assert len(symbols) == 40
    assert "601628.SH" in symbols


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
        {" date ": "NaN", "symbol": "600519.SH", "close": 8.0},
        {" date ": "0000-00-00", "symbol": "600519.SH", "close": 7.0},
    ])

    normalized = normalize_frame(frame)

    assert [row["date"] for row in normalized.rows] == ["", "", "", "20240102", "20240103"]
    assert all(len(row["date"]) == 8 for row in normalized.rows if row["date"])
    assert len(normalized) == 5


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


def test_panda_auth_file_uses_configured_state_directory(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from backend.skills import panda

    auth_manager = SimpleNamespace(_user_json_dir=None)
    monkeypatch.setattr(
        panda,
        "CONFIG",
        SimpleNamespace(panda_state_dir=str(tmp_path)),
    )

    panda._configure_panda_state_dir(SimpleNamespace(auth_manager=auth_manager))

    assert auth_manager._user_json_dir == str(tmp_path.resolve())


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


def test_stock_daily_uses_dynamic_request_dates(monkeypatch, tmp_path):
    from backend.skills import data

    captured = {}

    def fake_bundle(request):
        captured["request"] = request
        return types.SimpleNamespace(
            status="failed", datasets={}, warnings=["test unavailable"]
        )

    monkeypatch.setattr(
        data,
        "CONFIG",
        dataclasses.replace(CONFIG, cache_dir=str(tmp_path), data_mode="panda"),
    )
    monkeypatch.setattr("backend.skills.panda.build_market_data_bundle", fake_bundle)

    with pytest.raises(data.EvidenceUnavailable):
        data.get_stock_daily("300750.SZ")

    expected = data.ResearchRequest.from_payload({"symbol": "300750.SZ"})
    assert captured["request"].start_date == expected.start_date
    assert captured["request"].end_date == expected.end_date
