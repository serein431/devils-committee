"""Adapters for online QuantSkills and the project-owned weight-change study."""

from __future__ import annotations

import asyncio
import csv
import json
import math
import os
import tempfile
import time
from typing import Any, Callable

from ..config import CONFIG
from ..research_request import ResearchRequest
from . import cli
from .contracts import MarketDataBundle, SkillFinding, SkillResult


ONLINE_SKILLS: dict[str, tuple[str, list[str]]] = {
    "skill-corporate-action-adjustment-auditor": (
        "audit_adjustments.py",
        ["--return-tolerance", "0.02", "--jump-threshold", "0.21"],
    ),
    "skill-survivorship-universe-auditor": ("audit_universe.py", []),
    "skill-portfolio-liquidity-stress-test": (
        "stress_liquidity.py",
        [
            "--participation",
            "0.1",
            "--volume-shock",
            "0.5",
            "--horizon-days",
            "5",
            "--eta",
            "0.5",
        ],
    ),
}

_GENERIC_FINDING_IMPACT = (
    "Review the domain result and confirm whether the issue changes the research conclusion."
)

ADJUSTMENT_COLUMNS = [
    "symbol",
    "date",
    "close",
    "adj_close",
    "split_factor",
    "cash_dividend",
]
UNIVERSE_COLUMNS = [
    "symbol",
    "date",
    "listed_at",
    "delisted_at",
    "return",
    "delisting_return",
    "eligible",
]
LIQUIDITY_COLUMNS = [
    "symbol",
    "position_value",
    "adv",
    "spread_bps",
    "volatility",
]
INDEX_WEIGHT_STUDY_ID = "project-index-weight-change-study"
FACTOR_SKILL_ID = "skill-factor-ranking-sage"
FACTOR_FEATURES = [
    "open",
    "close",
    "volume",
    "amount",
    "market_cap",
    "turnover",
]
FACTOR_LABEL_HORIZON = 5
MIN_FACTOR_OBSERVATIONS = 60


def report_to_result(
    skill_id: str,
    report: dict[str, Any],
    mode: str,
    duration_ms: int,
    dataset_hashes: list[str],
    assumptions: list[str] | None = None,
    forced_warning: str = "",
) -> SkillResult:
    """Convert a QuantSkills report without turning missing evidence into success."""
    raw_status = report.get("status")
    if raw_status == "insufficient-evidence" or forced_warning:
        status = "insufficient-evidence"
    elif raw_status in {"pass", "fail", "warning"}:
        status = "success"
    else:
        status = "error"

    findings: list[SkillFinding] = []
    for item in report.get("findings", []) or []:
        if not isinstance(item, dict):
            continue
        evidence = item.get("evidence", {})
        if not isinstance(evidence, dict):
            evidence = {}
        reasons = evidence.get("reasons", [])
        if isinstance(reasons, list):
            reason_text = ", ".join(str(reason) for reason in reasons)
        else:
            reason_text = str(reasons) if reasons else ""
        impact = item.get("impact")
        claim = (
            reason_text
            if impact == _GENERIC_FINDING_IMPACT and reason_text
            else impact or reason_text or "QuantSkills finding"
        )
        refs = [
            str(value)
            for value in evidence.values()
            if isinstance(value, str) and value
        ]
        findings.append(SkillFinding(str(claim), refs[:5], 0.8))

    warnings = [str(item) for item in report.get("limitations", []) or []]
    if forced_warning:
        warnings.append(forced_warning)
    metrics = report.get("metrics") or report.get("input_summary") or {}
    metrics = dict(metrics) if isinstance(metrics, dict) else {}
    if findings:
        metrics.setdefault("finding_count", len(findings))
    return SkillResult(
        skill_id=skill_id,
        mode=mode,  # type: ignore[arg-type]
        status=status,
        duration_ms=duration_ms,
        dataset_hashes=sorted(set(dataset_hashes)),
        outcome=raw_status if raw_status in {"pass", "fail", "warning"} else None,
        assumptions=list(assumptions or []),
        metrics=metrics,
        findings=findings,
        warnings=warnings,
    )


def liquidity_parameters(
    request: ResearchRequest,
    avg_amount: float,
) -> tuple[dict[str, float], list[str]]:
    assumptions: list[str] = []
    position_value = request.portfolio_value
    if position_value is None:
        position_value = 100000.0
        assumptions.append("position_value=100000 CNY demo assumption")
    spread_bps = request.spread_bps
    if spread_bps is None:
        spread_bps = 10.0
        assumptions.append("spread_bps=10 demo assumption")
    return {
        "position_value": float(position_value),
        "adv": float(avg_amount),
        "spread_bps": float(spread_bps),
    }, assumptions


def error_result(
    skill_id: str,
    bundle: MarketDataBundle,
    warning: str,
) -> SkillResult:
    return SkillResult(
        skill_id=skill_id,
        mode=bundle.mode,
        status="error",
        duration_ms=0,
        dataset_hashes=bundle.dataset_hashes,
        warnings=[warning],
    )


def missing_input_result(
    skill_id: str,
    bundle: MarketDataBundle,
    required_datasets: list[str],
) -> SkillResult | None:
    missing = [name for name in required_datasets if name not in bundle.datasets]
    if not missing:
        return None
    noun = "dataset" if len(missing) == 1 else "datasets"
    return SkillResult(
        skill_id=skill_id,
        mode=bundle.mode,
        status="insufficient-evidence",
        duration_ms=0,
        dataset_hashes=bundle.dataset_hashes,
        warnings=[f"{' and '.join(missing)} {noun} unavailable"],
    )


def _read_records(bundle: MarketDataBundle, name: str) -> list[dict[str, Any]]:
    artifact = bundle.datasets.get(name)
    if artifact is None:
        raise ValueError(f"{name} dataset unavailable")
    if artifact.path.startswith("memory://"):
        raise ValueError(f"{name} dataset unreadable")
    try:
        import pandas as pd  # type: ignore

        frame = pd.read_parquet(artifact.path)
        return [dict(row) for row in frame.to_dict(orient="records")]
    except Exception:
        raise ValueError(f"{name} dataset unreadable") from None


def _first(row: dict[str, Any], *names: str, default: Any = "") -> Any:
    for name in names:
        value = row.get(name)
        if value is not None and value != "":
            return value
    return default


def _date_key(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.lower() in {"nan", "nat", "none", "null", "0000-00-00", "00000000"}:
        return ""
    if len(raw) >= 10 and raw[4] in "-/" and raw[7] in "-/":
        key = f"{raw[:4]}{raw[5:7]}{raw[8:10]}"
    else:
        key = raw[:8]
    if len(key) != 8 or not key.isdigit():
        return ""
    try:
        from datetime import datetime

        datetime.strptime(key, "%Y%m%d")
    except ValueError:
        return ""
    return key


def _iso_date(value: Any) -> str:
    """Render a date as YYYY-MM-DD, the format the event-study skill requires.

    Accepts the internal 8-digit key (YYYYMMDD) or already-hyphenated input;
    returns "" when the value is not a usable 8-digit date so callers can apply
    their own fallback instead of feeding the skill an invalid_event_date row.
    """
    key = _date_key(value)
    if len(key) == 8 and key.isdigit():
        return f"{key[:4]}-{key[4:6]}-{key[6:8]}"
    return ""


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _dates(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            _date_key(_first(row, "date", "trade_date", "effective_date"))
            for row in rows
            if _first(row, "date", "trade_date", "effective_date")
        }
    )


def _returns_by_date(rows: list[dict[str, Any]]) -> dict[str, float]:
    ordered = sorted(
        (
            _date_key(_first(row, "date", "trade_date")),
            _number(_first(row, "close", "close_price", "adj_close"), float("nan")),
        )
        for row in rows
        if _first(row, "date", "trade_date")
    )
    returns: dict[str, float] = {}
    previous: float | None = None
    for date, close in ordered:
        if previous is not None and previous != 0 and math.isfinite(close):
            returns[date] = close / previous - 1.0
        previous = close
    return returns


def _adjustment_rows(
    request: ResearchRequest,
    bundle: MarketDataBundle,
) -> tuple[list[dict[str, Any]], str]:
    daily = _read_records(bundle, "daily")
    # PandaData's post-adjusted series can omit otherwise valid trading days.
    # Use the complete pre-adjusted series so a missing adjusted row is never
    # backfilled with an incomparable raw close and reported as a false jump.
    adjusted = _read_records(bundle, "daily_pre")
    factors = _read_records(bundle, "adj_factor")
    dividend = (
        _read_records(bundle, "dividend")
        if "dividend" in bundle.datasets
        else []
    )
    cash_dividend = (
        _read_records(bundle, "cash_dividend")
        if "cash_dividend" in bundle.datasets
        else []
    )
    splits = (
        _read_records(bundle, "split")
        if "split" in bundle.datasets
        else []
    )
    raw_by_date = {
        _date_key(_first(row, "date", "trade_date")): _number(
            _first(row, "close", "close_price")
        )
        for row in daily
    }
    adjusted_by_date = {
        _date_key(_first(row, "date", "trade_date")): _number(
            _first(row, "close", "adj_close", "close_price")
        )
        for row in adjusted
    }
    # ``ex_factor`` is a vendor adjustment factor that can combine cash and
    # share events; it is deliberately not used as ``split_factor``. Keep
    # explicit split factors (when supplied) keyed by the ex-date.
    factor_by_date = {
        _date_key(_first(row, "ex_date", "date", "trade_date")): _number(
            _first(row, "split_factor", "factor"),
            1.0,
        )
        for row in factors
        if _date_key(_first(row, "ex_date", "date", "trade_date"))
    }
    split_by_date: dict[str, float] = {}
    for row in splits:
        event_date = _date_key(
            _first(row, "ex_date", "date", "trade_date")
        )
        pre = _number(_first(row, "split_factor_pre", "factor_pre"))
        post = _number(_first(row, "split_factor_post", "factor_post"))
        explicit = _number(_first(row, "split_factor", "factor"), 1.0)
        if event_date and pre > 0 and post > 0:
            split_by_date[event_date] = post / pre
        elif event_date and explicit > 0:
            split_by_date[event_date] = explicit
    cash_names = (
        "cash_dividend",
        "cash_amount",
        "dividend_amount",
        "cash_dividend_amount",
    )
    cash_available = any(
        any(name in row and row[name] not in (None, "") for name in cash_names)
        for row in dividend
    )
    cash_by_date: dict[str, float] = {}
    for row in cash_dividend:
        event_date = _date_key(
            _first(row, "ex_date", "date", "ex_dividend_date")
        )
        gross = _first(row, "div_cash_gross", *cash_names)
        amount = _number(gross, float("nan"))
        round_lot = _number(_first(row, "round_lot"), 1.0)
        if event_date and math.isfinite(amount) and round_lot > 0:
            # PandaData's cash-dividend response is quoted per round lot.
            cash_by_date[event_date] = amount / round_lot
            cash_available = True
    for row in dividend:
        event_date = _date_key(
            _first(
                row,
                "date",
                "ex_date",
                "ex_dividend_date",
                "record_date",
            )
        )
        if event_date and event_date not in cash_by_date:
            cash_by_date[event_date] = _number(_first(row, *cash_names))
    rows = [
        {
            "symbol": request.symbol,
            "date": _iso_date(date),
            "close": raw_by_date[date],
            "adj_close": adjusted_by_date.get(date, raw_by_date[date]),
            "split_factor": split_by_date.get(
                date, factor_by_date.get(date, 1.0)
            ),
            "cash_dividend": cash_by_date.get(date, 0.0),
        }
        for date in sorted(raw_by_date)
        if _iso_date(date)
    ]
    warning = "" if cash_available else "cash_dividend amount unavailable"
    return rows, warning


def _universe_rows(
    request: ResearchRequest,
    bundle: MarketDataBundle,
) -> tuple[list[dict[str, Any]], str]:
    start_rows = _read_records(bundle, "trade_list_start")
    end_rows = _read_records(bundle, "trade_list_end")
    status_rows = _read_records(bundle, "status_change")
    detail_rows = (
        _read_records(bundle, "stock_detail")
        if "stock_detail" in bundle.datasets
        else []
    )
    start_by_symbol = {
        str(_first(row, "symbol", "stock_symbol", "code")): row
        for row in start_rows
        if _first(row, "symbol", "stock_symbol", "code")
    }
    end_by_symbol = {
        str(_first(row, "symbol", "stock_symbol", "code")): row
        for row in end_rows
        if _first(row, "symbol", "stock_symbol", "code")
    }
    status_by_symbol: dict[str, dict[str, Any]] = {}
    detail_by_symbol = {
        str(_first(row, "symbol", "stock_symbol", "code")): row
        for row in detail_rows
        if _first(row, "symbol", "stock_symbol", "code")
    }
    delisting_return_available = False
    delisting_observed = False
    for row in status_rows:
        symbol = str(_first(row, "symbol", "stock_symbol", "code"))
        if not symbol:
            continue
        current = status_by_symbol.setdefault(symbol, {})
        for target, aliases in (
            ("listed_at", ("listed_at", "list_date", "listing_date")),
            ("delisted_at", ("delisted_at", "delist_date", "delisting_date")),
            ("return", ("return", "period_return")),
            ("delisting_return", ("delisting_return",)),
        ):
            value = _first(row, *aliases)
            if value not in (None, ""):
                current[target] = value
                if target == "delisting_return":
                    delisting_return_available = True
        if _date_key(
            _first(row, "delisted_at", "delist_date", "delisting_date")
        ):
            delisting_observed = True
    detail = detail_by_symbol.get(request.symbol, {})
    detail_delisted = _first(
        detail, "de_listed_date", "delisted_date", "delisted_at", "delist_date"
    )
    if _date_key(detail_delisted):
        delisting_observed = True
    output: list[dict[str, Any]] = []
    # The request concerns one security. Restrict the audit rows to that
    # security so a full-market trade-list snapshot does not create thousands
    # of rows with no lifecycle metadata for the requested sample.
    symbols = [request.symbol]
    for date, members in (
        (request.start_date, start_by_symbol),
        (request.end_date, end_by_symbol),
    ):
        for symbol in symbols:
            row = members.get(symbol, {})
            status = status_by_symbol.get(symbol, {})
            listed_at = _first(
                detail,
                "listed_date",
                "listed_at",
                "list_date",
                default=_first(status, "listed_at", "list_date", "listing_date"),
            )
            delisted_at = _first(
                detail,
                "de_listed_date",
                "delisted_date",
                "delisted_at",
                "delist_date",
                "delisting_date",
                default=_first(status, "delisted_at", "delist_date", "delisting_date"),
            )
            output.append(
                {
                    "symbol": symbol,
                    "date": _iso_date(date),
                    "listed_at": _iso_date(listed_at),
                    "delisted_at": _iso_date(delisted_at),
                    "return": _first(
                        row,
                        "return",
                        "period_return",
                        default=status.get("return", ""),
                    ),
                    "delisting_return": status.get("delisting_return", ""),
                    "eligible": 1 if symbol in members else 0,
                }
            )
    if not output:
        output.append(
            {
                "symbol": request.symbol,
                "date": request.end_date,
                "listed_at": "",
                "delisted_at": "",
                "return": "",
                "delisting_return": "",
                "eligible": 1,
            }
        )
    warnings: list[str] = []
    if not detail:
        warnings.append("stock_detail dataset unavailable; lifecycle dates incomplete")
    if delisting_observed and not delisting_return_available:
        warnings.append("delisting_return unavailable")
    warning = "; ".join(warnings)
    return output, warning


def _liquidity_rows(
    request: ResearchRequest,
    bundle: MarketDataBundle,
) -> tuple[list[dict[str, Any]], list[str], str]:
    daily = _read_records(bundle, "daily")
    amounts = [
        _number(
            _first(
                row,
                "amount",
                "turnover_amount",
                "trade_amount",
                "trading_value",
            )
        )
        for row in daily
    ]
    amounts = [amount for amount in amounts if amount > 0]
    avg_amount = sum(amounts) / len(amounts) if amounts else 0.0
    params, assumptions = liquidity_parameters(request, avg_amount)
    returns = list(_returns_by_date(daily).values())
    if len(returns) > 1:
        mean = sum(returns) / len(returns)
        variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
        volatility = math.sqrt(variance) * math.sqrt(252)
    else:
        volatility = 0.0
    warning = "" if amounts else "average traded amount unavailable"
    return (
        [{"symbol": request.symbol, **params, "volatility": volatility}],
        assumptions,
        warning,
    )


def _event_rows(
    request: ResearchRequest,
    bundle: MarketDataBundle,
) -> tuple[list[dict[str, Any]], str]:
    weights = _read_records(bundle, "index_weights")
    stock = _read_records(bundle, "daily")
    benchmark = _read_records(bundle, "index_daily")
    stock_returns = _returns_by_date(stock)
    benchmark_returns = _returns_by_date(benchmark)
    stock_volume = {
        _date_key(_first(row, "date", "trade_date")): _number(
            _first(row, "volume", "vol", "turnover_volume")
        )
        for row in stock
    }
    positive_volumes = [value for value in stock_volume.values() if value > 0]
    average_volume = (
        sum(positive_volumes) / len(positive_volumes)
        if positive_volumes
        else 0.0
    )
    event_rows: list[dict[str, Any]] = []
    ordered_weights = sorted(
        weights,
        key=lambda row: str(_first(row, "date", "effective_date", "trade_date")),
    )
    previous_weight: float | None = None
    event_count = 0
    trading_dates = _dates(stock)
    skipped_dates = 0
    for row in ordered_weights:
        weight_date = _date_key(
            _first(row, "effective_date", "date", "trade_date")
        )
        current_weight = _number(
            _first(row, "weight_after", "weight", "index_weight")
        )
        explicit_before = _first(row, "weight_before", default=None)
        if previous_weight is None and explicit_before is None:
            previous_weight = current_weight
            continue
        before = _number(explicit_before, previous_weight or 0.0)
        if not weight_date or math.isclose(current_weight, before, abs_tol=1e-12):
            previous_weight = current_weight
            continue
        event_count += 1
        event_id = str(_first(row, "event_id", default=f"event-{event_count}"))
        try:
            event_index = trading_dates.index(weight_date)
        except ValueError:
            skipped_dates += 1
            previous_weight = current_weight
            continue
        raw_action = str(_first(row, "action", "change_type", default="")).strip()
        if raw_action not in {"add", "delete", "weight_change"}:
            if before == 0 and current_weight > 0:
                raw_action = "add"
            elif before > 0 and current_weight == 0:
                raw_action = "delete"
            else:
                raw_action = "weight_change"
        weight_iso = _iso_date(weight_date)
        for offset in range(-5, 6):
            date_index = event_index + offset
            if not 0 <= date_index < len(trading_dates):
                continue
            date = trading_dates[date_index]
            # Skip window edges where a daily return cannot be computed (the
            # first day of each price series has no prior close). Feeding the
            # skill an empty string there trips its strict numeric validation
            # (invalid_numeric) and sinks an otherwise usable event study.
            if date not in stock_returns or date not in benchmark_returns:
                continue
            volume_ratio = (
                stock_volume.get(date, 0.0) / average_volume
                if average_volume > 0
                else 0.0
            )
            event_rows.append(
                {
                    "event_id": event_id,
                    "symbol": request.symbol,
                    "action": raw_action,
                    "weight_date": weight_iso,
                    "relative_day": offset,
                    "return": stock_returns[date],
                    "benchmark_return": benchmark_returns[date],
                    "volume_ratio": volume_ratio,
                    "weight_before": before,
                    "weight_after": current_weight,
                }
            )
        previous_weight = current_weight
    warning = "部分权重记录日期不是股票交易日" if skipped_dates else ""
    return event_rows, warning


def _weight_change_result(
    bundle: MarketDataBundle,
    rows: list[dict[str, Any]],
    duration_ms: int,
    warning: str = "",
) -> SkillResult:
    if not rows:
        return SkillResult(
            skill_id=INDEX_WEIGHT_STUDY_ID,
            mode=bundle.mode,
            status="insufficient-evidence",
            duration_ms=duration_ms,
            dataset_hashes=bundle.dataset_hashes,
            warnings=[
                warning
                or "请求区间内没有观察到指数权重变化"
            ],
        )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["event_id"]), []).append(row)

    findings: list[SkillFinding] = []
    event_cars: list[float] = []
    event_volume_ratios: list[float] = []
    for event_rows in grouped.values():
        first = event_rows[0]
        car = sum(
            _number(row.get("return")) - _number(row.get("benchmark_return"))
            for row in event_rows
        )
        volume_ratios = [_number(row.get("volume_ratio")) for row in event_rows]
        mean_volume_ratio = sum(volume_ratios) / len(volume_ratios)
        event_cars.append(car)
        event_volume_ratios.append(mean_volume_ratio)
        findings.append(
            SkillFinding(
                (
                    f"{first['weight_date']} 观察到指数权重从 "
                    f"{_number(first['weight_before']):.5f} 变为 "
                    f"{_number(first['weight_after']):.5f}；前后 5 个交易日累计超额收益 "
                    f"{car:.4%}，平均成交量比 {mean_volume_ratio:.2f}"
                ),
                ["index_weights", "daily", "index_daily", str(first["weight_date"])],
                0.8,
            )
        )

    hashes = [
        bundle.datasets[name].sha256
        for name in ("index_weights", "daily", "index_daily")
        if name in bundle.datasets
    ]
    warnings = [
        "PandaAI 未提供官方公告日期；本项只研究观察到的指数权重变化日期。"
    ]
    if warning:
        warnings.append(warning)
    return SkillResult(
        skill_id=INDEX_WEIGHT_STUDY_ID,
        mode=bundle.mode,
        status="success",
        duration_ms=duration_ms,
        dataset_hashes=sorted(set(hashes)),
        outcome="pass",
        assumptions=[
            "event_anchor=index_weight_observation_date",
            "abnormal_return=stock_return-index_return",
            "event_window=-5..+5 trading days",
        ],
        metrics={
            "event_anchor": "index_weight_observation_date",
            "event_count": len(grouped),
            "observation_count": len(rows),
            "mean_cumulative_abnormal_return": sum(event_cars) / len(event_cars),
            "mean_volume_ratio": sum(event_volume_ratios) / len(event_volume_ratios),
        },
        findings=findings,
        warnings=warnings,
    )


def _factor_inputs(
    request: ResearchRequest,
    bundle: MarketDataBundle,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
    dict[str, int],
    str,
]:
    raw_rows = _read_records(bundle, "factor")
    by_date: dict[str, dict[str, Any]] = {}
    for row in raw_rows:
        symbol = str(_first(row, "symbol", "ticker"))
        date = _date_key(_first(row, "date", "trade_date"))
        close = _number(_first(row, "close"), float("nan"))
        if symbol == request.symbol and date and math.isfinite(close) and close > 0:
            by_date[date] = row
    ordered = [(date, by_date[date]) for date in sorted(by_date)]
    labeled_count = len(ordered) - FACTOR_LABEL_HORIZON
    if labeled_count < MIN_FACTOR_OBSERVATIONS:
        return [], [], [], {}, "factor history is too short for a fixed split"

    candidates: dict[str, list[float]] = {name: [] for name in FACTOR_FEATURES}
    for _, row in ordered[:labeled_count]:
        for name in FACTOR_FEATURES:
            value = _number(row.get(name), float("nan"))
            if math.isfinite(value):
                candidates[name].append(value)
    features = [
        name
        for name, values in candidates.items()
        if len(values) >= MIN_FACTOR_OBSERVATIONS
        and len({round(value, 12) for value in values}) > 1
    ]
    if not features:
        return [], [], [], {}, "no usable numeric factor columns"

    feature_rows: list[dict[str, Any]] = []
    label_rows: list[dict[str, Any]] = []
    for index, (date, row) in enumerate(ordered[:labeled_count]):
        current_close = _number(row.get("close"), float("nan"))
        future_close = _number(
            ordered[index + FACTOR_LABEL_HORIZON][1].get("close"),
            float("nan"),
        )
        if not (
            math.isfinite(current_close)
            and current_close > 0
            and math.isfinite(future_close)
        ):
            continue
        feature_row: dict[str, Any] = {
            "date": date,
            "symbol": request.symbol,
            "available_date": date,
        }
        for name in features:
            value = _number(row.get(name), float("nan"))
            feature_row[name] = value if math.isfinite(value) else ""
        feature_rows.append(feature_row)
        label_rows.append(
            {
                "date": date,
                "symbol": request.symbol,
                "y": future_close / current_close - 1.0,
            }
        )

    if len(feature_rows) < MIN_FACTOR_OBSERVATIONS:
        return [], [], [], {}, "factor history is too short for a fixed split"
    valid_index = int(len(feature_rows) * 0.75)
    train_end_index = valid_index - FACTOR_LABEL_HORIZON - 1
    if train_end_index < 2 or valid_index >= len(feature_rows):
        return [], [], [], {}, "factor history cannot support an embargoed split"
    split = {
        "train_start": int(feature_rows[0]["date"]),
        "train_end": int(feature_rows[train_end_index]["date"]),
        "valid_start": int(feature_rows[valid_index]["date"]),
        "valid_end": int(feature_rows[-1]["date"]),
        "embargo_days": FACTOR_LABEL_HORIZON,
    }
    return feature_rows, label_rows, features, split, ""


class OnlineSkillRunner:
    def __init__(self, timeout_sec: float = 120) -> None:
        self.timeout_sec = min(float(timeout_sec), 120.0)

    def _invoke(
        self,
        skill_id: str,
        entry: str,
        rows: list[dict[str, Any]],
        columns: list[str],
        extra_args: list[str],
    ) -> tuple[dict[str, Any], int]:
        skill_dir = os.path.join(CONFIG.quantskills_dir, skill_id)
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "input.csv")
            output_path = os.path.join(temp_dir, "output.json")
            with open(input_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
            report = cli.invoke(
                skill_dir,
                entry,
                ["--input", input_path, "--out", output_path, *extra_args],
                timeout=max(1, int(math.ceil(self.timeout_sec))),
            )
        return report, round((time.monotonic() - started) * 1000)

    def _run(
        self,
        skill_id: str,
        bundle: MarketDataBundle,
        rows: list[dict[str, Any]],
        columns: list[str],
        assumptions: list[str] | None = None,
        forced_warning: str = "",
    ) -> SkillResult:
        if not rows:
            return SkillResult(
                skill_id=skill_id,
                mode=bundle.mode,
                status="insufficient-evidence",
                duration_ms=0,
                dataset_hashes=bundle.dataset_hashes,
                assumptions=list(assumptions or []),
                warnings=[forced_warning or "skill input unavailable"],
            )
        entry, extra_args = ONLINE_SKILLS[skill_id]
        report, duration_ms = self._invoke(
            skill_id, entry, rows, columns, extra_args
        )
        return report_to_result(
            skill_id,
            report,
            bundle.mode,
            duration_ms,
            bundle.dataset_hashes,
            assumptions=assumptions,
            forced_warning=forced_warning,
        )

    def run_adjustments(
        self, request: ResearchRequest, bundle: MarketDataBundle
    ) -> SkillResult:
        missing = missing_input_result(
            "skill-corporate-action-adjustment-auditor",
            bundle,
            ["daily", "daily_pre", "adj_factor"],
        )
        if missing is not None:
            return missing
        rows, warning = _adjustment_rows(request, bundle)
        return self._run(
            "skill-corporate-action-adjustment-auditor",
            bundle,
            rows,
            ADJUSTMENT_COLUMNS,
            forced_warning=warning,
        )

    def run_survivorship(
        self, request: ResearchRequest, bundle: MarketDataBundle
    ) -> SkillResult:
        missing = missing_input_result(
            "skill-survivorship-universe-auditor",
            bundle,
            ["status_change", "trade_list_start", "trade_list_end"],
        )
        if missing is not None:
            return missing
        rows, warning = _universe_rows(request, bundle)
        return self._run(
            "skill-survivorship-universe-auditor",
            bundle,
            rows,
            UNIVERSE_COLUMNS,
            forced_warning=warning,
        )

    def run_liquidity(
        self, request: ResearchRequest, bundle: MarketDataBundle
    ) -> SkillResult:
        rows, assumptions, warning = _liquidity_rows(request, bundle)
        return self._run(
            "skill-portfolio-liquidity-stress-test",
            bundle,
            rows,
            LIQUIDITY_COLUMNS,
            assumptions=assumptions,
            forced_warning=warning,
        )

    def run_index_event(
        self, request: ResearchRequest, bundle: MarketDataBundle
    ) -> SkillResult:
        missing = missing_input_result(
            INDEX_WEIGHT_STUDY_ID,
            bundle,
            ["index_weights", "daily", "index_daily"],
        )
        if missing is not None:
            return missing
        started = time.monotonic()
        rows, warning = _event_rows(request, bundle)
        return _weight_change_result(
            bundle,
            rows,
            round((time.monotonic() - started) * 1000),
            warning,
        )

    def run_factor_ranking(
        self, request: ResearchRequest, bundle: MarketDataBundle
    ) -> SkillResult:
        missing = missing_input_result(FACTOR_SKILL_ID, bundle, ["factor"])
        if missing is not None:
            return missing
        feature_rows, label_rows, features, split, warning = _factor_inputs(
            request, bundle
        )
        if warning:
            return SkillResult(
                skill_id=FACTOR_SKILL_ID,
                mode=bundle.mode,
                status="insufficient-evidence",
                duration_ms=0,
                dataset_hashes=[bundle.datasets["factor"].sha256],
                warnings=[warning],
            )

        skill_dir = os.path.join(CONFIG.quantskills_dir, FACTOR_SKILL_ID)
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as temp_dir:
            feature_path = os.path.join(temp_dir, "features.csv")
            label_path = os.path.join(temp_dir, "labels.csv")
            config_path = os.path.join(temp_dir, "factor-ranking.json")
            with open(feature_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["date", "symbol", "available_date", *features],
                )
                writer.writeheader()
                writer.writerows(feature_rows)
            with open(label_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=["date", "symbol", "y"]
                )
                writer.writeheader()
                writer.writerows(label_rows)
            config = {
                "run_name": f"factor-ranking-{request.symbol.replace('.', '-')}",
                "output_root": os.path.join(temp_dir, "output"),
                "mode": "mrmr",
                "selection_count": min(3, len(features)),
                "input": {
                    "feature_path": feature_path,
                    "label_path": label_path,
                },
                "data": {
                    "date_col": "date",
                    "ticker_col": "symbol",
                    "label_col": "y",
                    "feature_include": features,
                },
                "validation": {"method": "fixed", **split},
                "mrmr": {
                    "relevance": "f",
                    "redundancy": "c",
                    "denominator": "mean",
                },
            }
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(config, handle, ensure_ascii=False)
            report = cli.invoke(
                skill_dir,
                "run_factor_selection.py",
                ["--input", config_path],
                timeout=max(1, int(math.ceil(self.timeout_sec))),
            )
        duration_ms = round((time.monotonic() - started) * 1000)
        selected = report.get("selected_factors")
        if not isinstance(selected, list) or not selected:
            return SkillResult(
                skill_id=FACTOR_SKILL_ID,
                mode=bundle.mode,
                status="insufficient-evidence",
                duration_ms=duration_ms,
                dataset_hashes=[bundle.datasets["factor"].sha256],
                warnings=["mRMR found no factor with publishable relevance"],
            )
        selected_names = [str(item) for item in selected]
        return SkillResult(
            skill_id=FACTOR_SKILL_ID,
            mode=bundle.mode,
            status="success",
            duration_ms=duration_ms,
            dataset_hashes=[bundle.datasets["factor"].sha256],
            assumptions=[
                "label=5-trading-day forward return from adjusted factor close",
                "single-security time-series ranking; not a cross-sectional backtest",
            ],
            metrics={
                "n_obs": len(feature_rows),
                "train_start": split["train_start"],
                "train_end": split["train_end"],
                "valid_start": split["valid_start"],
                "valid_end": split["valid_end"],
                "label_horizon": FACTOR_LABEL_HORIZON,
                "selected_count": len(selected_names),
            },
            findings=[
                SkillFinding(
                    "mRMR selected factors for 5-trading-day forward return: "
                    + ", ".join(selected_names),
                    ["factor", "selected_factors.json", "input_manifest.json"],
                    0.75,
                )
            ],
        )

    async def run_all(
        self,
        request: ResearchRequest,
        bundle: MarketDataBundle,
    ) -> list[SkillResult]:
        calls: list[
            tuple[str, Callable[[ResearchRequest, MarketDataBundle], SkillResult]]
        ] = [
            (
                "skill-corporate-action-adjustment-auditor",
                self.run_adjustments,
            ),
            (
                "skill-survivorship-universe-auditor",
                self.run_survivorship,
            ),
            (
                "skill-portfolio-liquidity-stress-test",
                self.run_liquidity,
            ),
            (
                INDEX_WEIGHT_STUDY_ID,
                self.run_index_event,
            ),
            (FACTOR_SKILL_ID, self.run_factor_ranking),
        ]

        async def one(
            skill_id: str,
            call: Callable[[ResearchRequest, MarketDataBundle], SkillResult],
        ) -> SkillResult:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(call, request, bundle),
                    timeout=self.timeout_sec,
                )
            except asyncio.TimeoutError:
                return error_result(skill_id, bundle, "skill timed out")
            except Exception:
                return error_result(skill_id, bundle, "skill execution failed")

        return list(
            await asyncio.gather(
                *(one(skill_id, call) for skill_id, call in calls)
            )
        )
