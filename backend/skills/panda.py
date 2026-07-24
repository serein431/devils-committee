"""Build traceable market-data bundles from PandaData or verified cache files."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from ..config import CONFIG
from ..research_request import ResearchRequest
from .cache import DatasetCache
from .contracts import DatasetArtifact, MarketDataBundle


ParamsFactory = Callable[[ResearchRequest], dict[str, Any]]

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
    "status_change": (
        "get_stock_status_change",
        lambda r: {
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "fields": [],
        },
    ),
    "trade_list_start": (
        "get_trade_list",
        lambda r: {"date": r.start_date, "exchange": r.symbol[-2:]},
    ),
    "trade_list_end": (
        "get_trade_list",
        lambda r: {"date": r.end_date, "exchange": r.symbol[-2:]},
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
            clean[column] = clean[column].map(
                lambda value: (
                    ""
                    if value is None
                    else str(value).replace("-", "").split(".")[0]
                )
            )

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
    try:
        import panda_data  # type: ignore

        panda_data.init_token(
            username=CONFIG.panda_username,
            password=CONFIG.panda_password,
            base_url=CONFIG.panda_base_url,
        )
        sdk_version = str(getattr(panda_data, "__version__", None) or "0.0.12")
    except Exception:
        return MarketDataBundle.insufficient(
            request.symbol,
            "PandaData authentication unavailable",
        )

    datasets: dict[str, DatasetArtifact] = {}
    warnings: list[str] = []
    for name, (method_name, params_factory) in DATASET_CALLS.items():
        params = params_factory(request)
        cached = cache.load(name, method_name, params, sdk_version)
        if cached is not None:
            datasets[name] = cached
            continue

        try:
            frame = getattr(panda_data, method_name)(**params)
            if frame is None or len(frame) == 0:
                warnings.append(f"{name} returned no rows")
                continue
            normalized = normalize_frame(frame)
            if len(normalized) == 0:
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
        return MarketDataBundle.insufficient(
            request.symbol,
            "daily dataset unavailable",
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
