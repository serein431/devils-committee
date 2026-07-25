"""Build traceable market-data bundles from PandaData or verified cache files."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date, datetime
from numbers import Real
from typing import Any, Callable

from ..config import CONFIG
from ..research_request import ResearchRequest
from .cache import DatasetCache
from .contracts import DatasetArtifact, MarketDataBundle


ParamsFactory = Callable[[ResearchRequest], dict[str, Any]]

# PandaData uses "SH" as the A-share market selector here and returns both
# Shanghai and Shenzhen symbols. The endpoint does not accept "SZ".
A_SHARE_TRADE_LIST_EXCHANGE = "SH"


def _quarter(value: str) -> tuple[int, int]:
    """Translate one YYYYMMDD boundary to PandaData's YYYYqN format."""

    parsed = datetime.strptime(value, "%Y%m%d")
    return parsed.year, (parsed.month - 1) // 3 + 1


def _financial_report_params(request: ResearchRequest) -> dict[str, Any]:
    """Fetch enough statements for the latest report and its YoY comparator."""

    start_year, start_quarter = _quarter(request.start_date)
    end_year, end_quarter = _quarter(request.end_date)
    # Even a narrow user-selected price window still needs the prior-year
    # statement to calculate like-for-like growth for the latest quarter.
    comparison_year = end_year - 1
    if (start_year, start_quarter) > (comparison_year, end_quarter):
        start_year, start_quarter = comparison_year, end_quarter
    return {
        "symbol": request.symbol,
        "start_quarter": f"{start_year}q{start_quarter}",
        "end_quarter": f"{end_year}q{end_quarter}",
        "date": request.end_date,
        "is_latest": True,
        # The statement schema differs across industries. Asking for the full
        # authorized report avoids silently dropping insurance/bank fields.
        "fields": [],
    }


def _quarter_range(request: ResearchRequest) -> tuple[str, str]:
    params = _financial_report_params(request)
    return str(params["start_quarter"]), str(params["end_quarter"])


def _intraday_requested(request: ResearchRequest) -> bool:
    question = request.question.lower()
    return any(
        token in question
        for token in ("盘中", "实时", "分钟", "intraday", "real-time", "realtime")
    )


def _management_detail_requested(request: ResearchRequest) -> bool:
    return any(
        token in request.question
        for token in ("调研", "管理层", "投资者关系", "机构问答", "路演")
    )


def _macro_calendar_requested(request: ResearchRequest) -> bool:
    return any(
        token in request.question
        for token in ("宏观日历", "经济日历", "事件日历", "数据公布")
    )

DATASET_CALLS: dict[str, tuple[str, ParamsFactory]] = {
    "daily": (
        "get_stock_daily",
        lambda r: {
            "symbol": [r.symbol],
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
            "indicator": "000300",
            "st": True,
        },
    ),
    "daily_pre": (
        "get_stock_daily_pre",
        lambda r: {
            "symbol": [r.symbol],
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
            "indicator": "000300",
            "st": True,
        },
    ),
    "daily_post": (
        "get_stock_daily_post",
        lambda r: {
            "symbol": [r.symbol],
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
            "indicator": "000300",
            "st": True,
        },
    ),
    "adj_factor": (
        "get_adj_factor",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "dividend": (
        "get_stock_dividend",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
        },
    ),
    "cash_dividend": (
        "get_stock_cash_dividend",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "split": (
        "get_stock_split",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "status_change": (
        "get_stock_status_change",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "stock_detail": (
        "get_stock_detail",
        lambda r: {
            "symbol": [r.symbol],
            "fields": [],
            "status": None,
        },
    ),
    "industry": (
        "get_stock_industry",
        lambda r: {
            "stock_symbol": r.symbol,
            "level": "L1",
        },
    ),
    "financial_performance": (
        "get_fina_performance",
        lambda r: {
            "symbol": r.symbol,
            "fields": [
                "symbol",
                "info_date",
                "end_date",
                "operating_revenue",
                "net_profit_parent",
                "net_profit_excluding_nonrecurring",
                "net_cash_flow_operating",
                "equity_parent",
                "equity_parent_common",
                "basic_eps",
                "eps_weighted",
                "roe_weighted",
                "roe_diluted",
                "bvps",
                "operating_revenue_yoy",
                "net_profit_parent_yoy",
                "net_profit_excluding_nonrecurring_yoy",
                "net_cash_flow_operating_yoy",
            ],
        },
    ),
    "financial_reports": (
        "get_fina_reports",
        _financial_report_params,
    ),
    "industry_detail": (
        "get_industry_detail",
        lambda r: {"level": "L1", "fields": []},
    ),
    "equity_nature": (
        "get_stock_equity_nature",
        lambda r: {"symbol": r.symbol, "fields": []},
    ),
    "index_indicator": (
        "get_index_indicator",
        lambda r: {
            "symbol": "000300.SH",
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "financial_forecast": (
        "get_fina_forecast",
        lambda r: {
            "symbol": r.symbol,
            "end_quarter": _quarter_range(r)[1],
            "fields": [],
        },
    ),
    "audit_opinion": (
        "get_audit_opinion",
        lambda r: {
            "symbol": r.symbol,
            "start_quarter": _quarter_range(r)[0],
            "end_quarter": _quarter_range(r)[1],
            "fields": [],
            "market": "cn",
        },
    ),
    "disclosure_schedule": (
        "get_stock_disclosure_date",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "share_float": (
        "get_share_float",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "margin": (
        "get_margin",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "northbound_holding": (
        "get_hsgt_hold",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "block_trade": (
        "get_block_trade",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "lhb_list": (
        "get_lhb_list",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "holder_count": (
        "get_holder_count",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "top_holders": (
        "get_top_holders",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
            "market": "cn",
            "start_rank": 1,
            "end_rank": 10,
            "stock_type": "total",
        },
    ),
    "stock_pledge": (
        "get_stock_pledge",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "shareholder_change": (
        "get_stock_shareholder_change",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "equity_placard": (
        "get_stock_equity_placard",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "repurchase": (
        "get_repurchase",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "restricted_release": (
        "get_restricted_list",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
            "market": "cn",
        },
    ),
    "dividend_amount": (
        "get_stock_dividend_amount",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "private_placement": (
        "get_stock_private_placement",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "allotment": (
        "get_stock_allotment",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "litigation": (
        "get_stock_litigation_arbitration",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "related_party": (
        "get_stock_related_party",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "guarantee": (
        "get_cumu_guarantee",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "material_contract": (
        "get_stock_material_contract",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "equity_illegal": (
        "get_stock_equity_illegal",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "investor_activity": (
        "get_investor_activity",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "investor_brief": (
        "get_investor_brief_detail",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "macro_ir": (
        "get_macro_ir",
        lambda r: {
            "symbol": ["IR0004522", "IR0003622"],
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "macro_mb": (
        "get_macro_mb",
        lambda r: {
            "symbol": ["MB0000004", "MB0000006"],
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "macro_calendar": (
        "get_macro_cal",
        lambda r: {
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "stock_rt_daily": (
        "get_stock_rt_daily",
        lambda r: {"symbol": r.symbol, "fields": []},
    ),
    "stock_minute": (
        "get_stock_min",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.end_date,
            "end_date": r.end_date,
            "fields": [],
            "frequency": "5m",
        },
    ),
    "stock_rt_minute": (
        "get_stock_rt_min",
        lambda r: {"symbol": r.symbol, "fields": [], "frequency": "1m"},
    ),
    "index_minute": (
        "get_index_min",
        lambda r: {
            "symbol": "000300.SH",
            "start_date": r.end_date,
            "end_date": r.end_date,
            "fields": [],
            "frequency": "5m",
        },
    ),
    "trade_list_start": (
        "get_trade_list",
        lambda r: {
            "date": r.start_date,
            "exchange": A_SHARE_TRADE_LIST_EXCHANGE,
        },
    ),
    "trade_list_end": (
        "get_trade_list",
        lambda r: {
            "date": r.end_date,
            "exchange": A_SHARE_TRADE_LIST_EXCHANGE,
        },
    ),
    "index_weights": (
        "get_index_weights",
        lambda r: {
            "index_symbol": "000300.SH",
            "stock_symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "index_daily": (
        "get_index_daily",
        lambda r: {
            "symbol": ["000300.SH"],
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "factor": (
        "get_factor",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "factors": [
                "open",
                "close",
                "volume",
                "amount",
                "market_cap",
                "turnover",
            ],
            "index_component": "000300",
            "type": "stock",
        },
    ),
}

SENSITIVE_COLUMN_PARTS = {
    "authorization",
    "token",
    "password",
    "secret",
    "cookie",
}

VALID_EMPTY_DATASETS = {
    "status_change",
    "dividend",
    "cash_dividend",
    "split",
    # A company need not publish a separate performance express report. Its
    # quarterly statements are fetched independently via financial_reports.
    "financial_performance",
    "financial_forecast",
    "audit_opinion",
    "disclosure_schedule",
    "margin",
    "northbound_holding",
    "block_trade",
    "lhb_list",
    "lhb_detail",
    "holder_count",
    "top_holders",
    "stock_pledge",
    "shareholder_change",
    "equity_placard",
    "repurchase",
    "restricted_release",
    "dividend_amount",
    "private_placement",
    "allotment",
    "litigation",
    "related_party",
    "guarantee",
    "material_contract",
    "equity_illegal",
    "investor_activity",
    "investor_brief",
    "macro_ir",
    "macro_mb",
    "macro_sector",
    "macro_calendar",
    "stock_rt_daily",
    "stock_minute",
    "stock_rt_minute",
    "index_minute",
}

CORE_DATASET_NAMES = {
    "daily",
    "daily_pre",
    "daily_post",
    "adj_factor",
    "dividend",
    "cash_dividend",
    "split",
    "status_change",
    "stock_detail",
    "industry",
    "financial_performance",
    "financial_reports",
    "trade_list_start",
    "trade_list_end",
    "index_weights",
    "index_daily",
    "factor",
}

DEFAULT_RESEARCH_DATASET_NAMES = {
    "industry_detail",
    "equity_nature",
    "index_indicator",
    "financial_forecast",
    "audit_opinion",
    "disclosure_schedule",
    "share_float",
    "margin",
    "northbound_holding",
    "block_trade",
    "lhb_list",
    "holder_count",
    "top_holders",
    "stock_pledge",
    "shareholder_change",
    "equity_placard",
    "repurchase",
    "restricted_release",
    "dividend_amount",
    "private_placement",
    "allotment",
    "litigation",
    "related_party",
    "guarantee",
    "material_contract",
    "equity_illegal",
    "investor_activity",
    "macro_ir",
    "macro_mb",
}

SDK_METHOD_ALIASES = {
    "get_stock_equity_nature": ("market_reference_reader", "get_equity_nature"),
    "get_stock_equity_placard": ("market_reference_reader", "get_equity_placard"),
    "get_stock_equity_illegal": ("market_reference_reader", "get_equity_illegal"),
    "get_stock_disclosure_date": ("market_reference_reader", "get_stock_disclosure_date"),
    "get_stock_litigation_arbitration": ("market_reference_reader", "get_stock_litigation_arbitration"),
    "get_stock_related_party": ("market_reference_reader", "get_stock_rela_party_trans"),
    "get_cumu_guarantee": ("market_reference_reader", "get_cumu_guarantee"),
    "get_stock_material_contract": ("market_reference_reader", "get_stock_material_contract"),
    "get_investor_brief_detail": ("market_reference_reader", "get_investor_brief_detail"),
}

MACRO_SECTOR_BY_INDUSTRY = {
    "非银金融": ("get_macro_fs", ["FS0000002"]),
    "银行": ("get_macro_fs", ["FS0000002"]),
    "电子": ("get_macro_ee", ["EE0017443"]),
    "电力设备": ("get_macro_ep", ["EP0000399", "EP0000400"]),
    "食品饮料": ("get_macro_fb", ["FB0045844", "FB0045846"]),
}

_TIME_SUFFIX = (
    r"(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?)?"
)
_COMPACT_DATE = re.compile(r"^(\d{8})(?:\.0+)?$")
_COMPACT_DATETIME = re.compile(rf"^(\d{{8}}){_TIME_SUFFIX}$")
_SEPARATED_DATE = re.compile(
    rf"^(\d{{4}})[-/](\d{{1,2}})[-/](\d{{1,2}}){_TIME_SUFFIX}$"
)
_MISSING_DATE_STRINGS = {"nan", "nat", "none", "null", "0000-00-00", "00000000"}


def _configure_panda_state_dir(panda_data: Any) -> None:
    """Keep PandaData's encrypted login file outside the read-only code tree."""
    state_dir = CONFIG.panda_state_dir.strip()
    if not state_dir:
        return
    os.makedirs(state_dir, exist_ok=True)
    auth_manager = getattr(panda_data, "auth_manager", None)
    if auth_manager is None:
        from panda_data import auth_manager

    auth_manager._user_json_dir = os.path.abspath(state_dir)


def _date_value_is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        pd = None
    if pd is not None:
        try:
            missing = pd.isna(value)
        except Exception:
            missing = False
        if isinstance(missing, bool) or type(missing).__name__ == "bool_":
            return bool(missing)
    if isinstance(value, Real):
        try:
            return math.isnan(float(value))
        except (TypeError, ValueError):
            return False
    return False


def _normalize_date_value(value: Any) -> str:
    """Normalize one scalar date without importing pandas on mock-only paths."""
    if _date_value_is_missing(value):
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y%m%d")

    raw = str(value).strip()
    if not raw:
        return ""
    if raw.lower() in _MISSING_DATE_STRINGS:
        return ""
    match = _COMPACT_DATE.fullmatch(raw) or _COMPACT_DATETIME.fullmatch(raw)
    if match:
        normalized = match.group(1)
    else:
        separated = _SEPARATED_DATE.fullmatch(raw)
        if separated is None:
            raise ValueError("invalid date value")
        year, month, day = separated.groups()
        normalized = f"{year}{int(month):02d}{int(day):02d}"

    try:
        datetime.strptime(normalized, "%Y%m%d")
    except ValueError:
        raise ValueError("invalid date value") from None
    if re.fullmatch(r"\d{8}", normalized) is None:
        raise ValueError("invalid date value")
    return normalized


def _normalize_missing_scalar(value: Any) -> Any:
    if isinstance(value, str) and value.strip().lower() in {
        "nan",
        "nat",
        "none",
        "null",
    }:
        return None
    return value


def normalize_frame(frame: Any) -> Any:
    """Return a sorted, deduplicated frame without sensitive columns."""
    clean = frame.copy()
    renamed = {column: str(column).strip() for column in clean.columns}
    clean = clean.rename(columns=renamed)
    lowered = {str(column).lower() for column in clean.columns}
    if any(
        part in column
        for column in lowered
        for part in SENSITIVE_COLUMN_PARTS
    ):
        raise ValueError("sensitive column rejected")

    for column in clean.columns:
        clean[column] = clean[column].map(_normalize_missing_scalar)
        if column == "date" or column.endswith("_date"):
            clean[column] = clean[column].map(_normalize_date_value)

    order = [
        column
        for column in ("date", "symbol", "stock_symbol", "index_symbol")
        if column in clean.columns
    ]
    if order:
        clean = clean.sort_values(by=order)
    return clean.drop_duplicates().reset_index(drop=True)


def build_mock_bundle(request: ResearchRequest) -> MarketDataBundle:
    """Build an explicitly synthetic, deterministic offline bundle."""
    from .data import _mock_bars

    bars = _mock_bars(request.symbol)
    payload = json.dumps(
        {
            "symbol": bars.symbol,
            "dates": bars.dates,
            "close": bars.close,
            "volume": bars.volume,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    artifact = DatasetArtifact(
        name="daily",
        method="mock_daily",
        params={"symbol": request.symbol},
        path=f"memory://mock/{request.symbol}",
        sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        rows=bars.n,
        mode="mock",
        fetched_at="deterministic",
    )
    return MarketDataBundle(
        request.symbol,
        "success",
        "mock",
        {"daily": artifact},
    )


def resolve_request_trading_dates(request: ResearchRequest) -> ResearchRequest:
    """Resolve research boundaries to actual A-share trading dates."""

    if CONFIG.data_mode != "panda" or not request.supported:
        return request
    try:
        import panda_data  # type: ignore

        _configure_panda_state_dir(panda_data)
        panda_data.init_token(
            username=CONFIG.panda_username,
            password=CONFIG.panda_password,
            base_url=CONFIG.panda_base_url,
        )
        frame = panda_data.get_trade_cal(
            start_date=request.start_date,
            end_date=request.end_date,
            exchange=A_SHARE_TRADE_LIST_EXCHANGE,
            is_trading_day=1,
            fields=["nature_date"],
        )
        if frame is None or len(frame) == 0:
            return request
        values = frame["nature_date"].tolist()
        dates = sorted(
            normalized
            for value in values
            if (normalized := _normalize_date_value(value))
        )
        if not dates:
            return request
        return replace(request, start_date=dates[0], end_date=dates[-1])
    except Exception:
        return request


def _resolve_sdk_method(panda_data: Any, method_name: str) -> Callable[..., Any]:
    direct = getattr(panda_data, method_name, None)
    if direct is not None:
        return direct
    module_name, alias = SDK_METHOD_ALIASES[method_name]
    module = getattr(panda_data, module_name, None)
    if module is None:
        from panda_data.readers import market_reference_reader

        modules = {"market_reference_reader": market_reference_reader}
        module = modules[module_name]
    return getattr(module, alias)


def _selected_dataset_names(request: ResearchRequest) -> set[str]:
    names = set(CORE_DATASET_NAMES | DEFAULT_RESEARCH_DATASET_NAMES)
    if _management_detail_requested(request):
        names.add("investor_brief")
    if _macro_calendar_requested(request):
        names.add("macro_calendar")
    if _intraday_requested(request):
        names.update(
            {"stock_rt_daily", "stock_minute", "stock_rt_minute", "index_minute"}
        )
    return names


def _artifact_records(artifact: DatasetArtifact | None) -> list[dict[str, Any]]:
    if artifact is None or artifact.path.startswith("memory://"):
        return []
    try:
        import pandas as pd  # type: ignore

        frame = pd.read_parquet(artifact.path)
        return [dict(row) for row in frame.to_dict(orient="records")]
    except Exception:
        return []


def _load_or_fetch_calls(
    *,
    cache: DatasetCache,
    panda_data: Any,
    sdk_version: str,
    calls: dict[str, tuple[str, dict[str, Any]]],
    datasets: dict[str, DatasetArtifact],
    authenticated: bool,
) -> list[str]:
    warnings: list[str] = []
    missing: list[tuple[str, str, dict[str, Any]]] = []
    for name, (method_name, params) in calls.items():
        if name in datasets:
            continue
        cached = cache.load(name, method_name, params, sdk_version)
        if cached is not None:
            datasets[name] = cached
        else:
            missing.append((name, method_name, params))

    if not missing or not authenticated or panda_data is None:
        return warnings

    def fetch_one(
        item: tuple[str, str, dict[str, Any]],
    ) -> tuple[str, DatasetArtifact | None, str | None]:
        name, method_name, params = item
        method = _resolve_sdk_method(panda_data, method_name)
        try:
            frame = method(**params)
            if frame is None:
                return name, None, f"{name} returned no rows"
            normalized = normalize_frame(frame)
            if len(normalized) == 0 and name not in VALID_EMPTY_DATASETS:
                return name, None, f"{name} returned no rows"
            artifact = cache.save(
                name,
                method_name,
                params,
                sdk_version,
                normalized,
            )
            return name, artifact, None
        except Exception:
            return name, None, f"{name} request failed"

    workers = min(6, len(missing))
    failed: list[tuple[str, str, dict[str, Any]]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_one, item): item[0] for item in missing}
        for future in as_completed(futures):
            name, artifact, warning = future.result()
            if artifact is not None:
                datasets[name] = artifact
            elif warning == f"{name} request failed":
                failed.append(next(item for item in missing if item[0] == name))
            elif warning:
                warnings.append(warning)

    # A few PandaData readers are reliable in isolation but can fail while
    # dozens of other SDK calls are active. Retry those transport failures only
    # after the parallel batch has drained; empty datasets remain empty.
    for item in failed:
        name, artifact, warning = fetch_one(item)
        if artifact is not None:
            datasets[name] = artifact
        elif warning:
            warnings.append(f"{name} request failed after serial retry")
    return warnings


def _dynamic_calls(
    request: ResearchRequest,
    datasets: dict[str, DatasetArtifact],
) -> dict[str, tuple[str, dict[str, Any]]]:
    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    industry_rows = _artifact_records(datasets.get("industry"))
    industry_row = industry_rows[-1] if industry_rows else {}
    industry_code = str(industry_row.get("industry_code") or "").strip()
    industry_name = str(industry_row.get("industry_name") or "").strip()
    if industry_code:
        calls["industry_peers"] = (
            "get_industry_constituents",
            {"industry_code": industry_code, "level": "L1", "fields": []},
        )
    macro_route = MACRO_SECTOR_BY_INDUSTRY.get(industry_name)
    if macro_route:
        method_name, symbols = macro_route
        calls["macro_sector"] = (
            method_name,
            {
                "symbol": symbols,
                "start_date": request.start_date,
                "end_date": request.end_date,
                "fields": [],
            },
        )

    lhb_rows = _artifact_records(datasets.get("lhb_list"))
    if lhb_rows:
        calls["lhb_detail"] = (
            "get_lhb_detail",
            {
                "symbol": request.symbol,
                "start_date": request.start_date,
                "end_date": request.end_date,
                "fields": [],
            },
        )
    return calls


def _peer_factor_call(
    request: ResearchRequest,
    datasets: dict[str, DatasetArtifact],
) -> dict[str, tuple[str, dict[str, Any]]]:
    rows = _artifact_records(datasets.get("industry_peers"))
    active = []
    for row in rows:
        symbol = str(row.get("stock_symbol") or "").strip()
        in_date = _date_key_for_route(row.get("in_date"))
        out_date = _date_key_for_route(row.get("out_date"))
        if not symbol or (in_date and in_date > request.end_date):
            continue
        if out_date and out_date <= request.end_date:
            continue
        active.append(symbol)
    peers = [symbol for symbol in sorted(set(active)) if symbol != request.symbol]
    symbols = peers[:39] + [request.symbol]
    if len(symbols) < 2:
        return {}
    end = datetime.strptime(request.end_date, "%Y%m%d")
    peer_start = max(
        request.start_date,
        date.fromordinal(end.date().toordinal() - 200).strftime("%Y%m%d"),
    )
    return {
        "industry_peer_factors": (
            "get_factor",
            {
                "symbol": symbols,
                "start_date": peer_start,
                "end_date": request.end_date,
                "factors": ["close", "amount", "market_cap", "turnover"],
                "type": "stock",
            },
        )
    }


def _date_key_for_route(value: Any) -> str:
    try:
        return _normalize_date_value(value)
    except ValueError:
        return ""


def build_market_data_bundle(request: ResearchRequest) -> MarketDataBundle:
    """Fetch all known datasets without ever masking live failure with mock data."""
    if not request.supported:
        return MarketDataBundle.insufficient(
            request.symbol,
            "current live research supports A shares only",
        )
    if CONFIG.data_mode == "mock":
        return build_mock_bundle(request)

    cache = DatasetCache(CONFIG.cache_dir, CONFIG.data_version)
    panda_data = None
    try:
        import panda_data  # type: ignore
        _configure_panda_state_dir(panda_data)
        sdk_version = str(getattr(panda_data, "__version__", None) or "0.0.12")
    except Exception:
        sdk_version = "0.0.12"

    datasets: dict[str, DatasetArtifact] = {}
    warnings: list[str] = []
    selected = _selected_dataset_names(request)
    calls = {
        name: (DATASET_CALLS[name][0], DATASET_CALLS[name][1](request))
        for name in selected
    }
    missing_exists = any(
        cache.load(name, method, params, sdk_version) is None
        for name, (method, params) in calls.items()
    )
    authenticated = False
    if missing_exists:
        if panda_data is None:
            warnings.append("PandaData authentication unavailable")
        else:
            try:
                panda_data.init_token(
                    username=CONFIG.panda_username,
                    password=CONFIG.panda_password,
                    base_url=CONFIG.panda_base_url,
                )
                authenticated = True
            except Exception:
                warnings.append("PandaData authentication unavailable")

    warnings.extend(
        _load_or_fetch_calls(
            cache=cache,
            panda_data=panda_data,
            sdk_version=sdk_version,
            calls=calls,
            datasets=datasets,
            authenticated=authenticated,
        )
    )
    dynamic = _dynamic_calls(request, datasets)
    warnings.extend(
        _load_or_fetch_calls(
            cache=cache,
            panda_data=panda_data,
            sdk_version=sdk_version,
            calls=dynamic,
            datasets=datasets,
            authenticated=authenticated,
        )
    )
    peers = _peer_factor_call(request, datasets)
    warnings.extend(
        _load_or_fetch_calls(
            cache=cache,
            panda_data=panda_data,
            sdk_version=sdk_version,
            calls=peers,
            datasets=datasets,
            authenticated=authenticated,
        )
    )

    if "daily" not in datasets:
        return MarketDataBundle(
            symbol=request.symbol,
            status="insufficient-evidence",
            mode="cache" if datasets else "live",
            datasets=datasets,
            warnings=[*warnings, "daily dataset unavailable"],
        )
    mode = (
        "live"
        if any(artifact.mode == "live" for artifact in datasets.values())
        else "cache"
    )
    return MarketDataBundle(
        request.symbol,
        "success",
        mode,
        datasets,
        sorted(set(warnings)),
    )
