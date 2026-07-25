"""Build traceable market-data bundles from PandaData or verified cache files."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
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

VALID_EMPTY_DATASETS = {"status_change", "dividend", "cash_dividend", "split"}

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
    missing: list[tuple[str, str, dict[str, Any]]] = []
    for name, (method_name, params_factory) in DATASET_CALLS.items():
        params = params_factory(request)
        cached = cache.load(name, method_name, params, sdk_version)
        if cached is not None:
            datasets[name] = cached
            continue
        missing.append((name, method_name, params))

    authenticated = False
    if missing:
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

    if authenticated:
        for name, method_name, params in missing:
            try:
                frame = getattr(panda_data, method_name)(**params)
                if frame is None:
                    warnings.append(f"{name} returned no rows")
                    continue
                normalized = normalize_frame(frame)
                if len(normalized) == 0:
                    if name in VALID_EMPTY_DATASETS:
                        datasets[name] = cache.save(
                            name,
                            method_name,
                            params,
                            sdk_version,
                            normalized,
                        )
                        continue
                    warnings.append(f"{name} returned no rows")
                    continue
                datasets[name] = cache.save(
                    name,
                    method_name,
                    params,
                    sdk_version,
                    normalized,
                )
            except Exception:
                warnings.append(f"{name} request failed")

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
        warnings,
    )
