"""Project-owned company research profiles built from one PandaData bundle.

These profiles are analysis evidence, not independent audit verdicts. They give
the research agents enough company, valuation and market context to discuss the
security itself while the existing QuantSkills remain the audit layer.
"""

from __future__ import annotations

import math
import statistics
import time
from datetime import datetime
from typing import Any

from ..research_request import ResearchRequest
from .contracts import MarketDataBundle, SkillFinding, SkillResult
from .data import _mock_bars, stable_seed


FUNDAMENTAL_PROFILE_ID = "project-company-fundamentals"
VALUATION_PROFILE_ID = "project-valuation-snapshot"
MARKET_PROFILE_ID = "project-market-behavior"
COMPANY_PROFILE_ID = "project-company-context"
INDUSTRY_PROFILE_ID = "project-industry-comparison"
FLOW_PROFILE_ID = "project-capital-flow"
OWNERSHIP_PROFILE_ID = "project-ownership-and-capital-actions"
EVENT_PROFILE_ID = "project-corporate-events"
MACRO_PROFILE_ID = "project-macro-environment"
RESEARCH_PROFILE_IDS = [
    COMPANY_PROFILE_ID,
    FUNDAMENTAL_PROFILE_ID,
    VALUATION_PROFILE_ID,
    MARKET_PROFILE_ID,
    INDUSTRY_PROFILE_ID,
    FLOW_PROFILE_ID,
    OWNERSHIP_PROFILE_ID,
    EVENT_PROFILE_ID,
    MACRO_PROFILE_ID,
]

RESEARCH_DATASET_NAMES = (
    "daily",
    "daily_pre",
    "factor",
    "index_daily",
    "index_indicator",
    "index_weights",
    "financial_reports",
    "financial_performance",
    "financial_forecast",
    "audit_opinion",
    "disclosure_schedule",
    "stock_detail",
    "industry",
    "industry_detail",
    "industry_peers",
    "industry_peer_factors",
    "equity_nature",
    "status_change",
    "share_float",
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
)


def build_research_profiles(
    request: ResearchRequest,
    bundle: MarketDataBundle,
) -> dict[str, SkillResult]:
    """Build three traceable analysis profiles without changing Skill manifests."""

    if bundle.mode == "mock":
        return _mock_profiles(request, bundle)

    records = {
        name: _read_records(bundle, name)
        for name in RESEARCH_DATASET_NAMES
        if name in bundle.datasets
    }
    return {
        COMPANY_PROFILE_ID: _company_profile(bundle, records),
        FUNDAMENTAL_PROFILE_ID: _fundamental_profile(bundle, records),
        VALUATION_PROFILE_ID: _valuation_profile(bundle, records),
        MARKET_PROFILE_ID: _market_profile(bundle, records),
        INDUSTRY_PROFILE_ID: _industry_profile(bundle, records),
        FLOW_PROFILE_ID: _flow_profile(bundle, records),
        OWNERSHIP_PROFILE_ID: _ownership_profile(request, bundle, records),
        EVENT_PROFILE_ID: _event_profile(request, bundle, records),
        MACRO_PROFILE_ID: _macro_profile(request, bundle, records),
    }


def _read_records(bundle: MarketDataBundle, name: str) -> list[dict[str, Any]]:
    artifact = bundle.datasets.get(name)
    if artifact is None or artifact.path.startswith("memory://"):
        return []
    try:
        import pandas as pd  # type: ignore

        frame = pd.read_parquet(artifact.path)
        return [dict(row) for row in frame.to_dict(orient="records")]
    except Exception:
        return []


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _date_key(value: Any) -> str:
    raw = str(value or "").strip().replace("-", "").replace("/", "")
    return raw[:8] if len(raw) >= 8 and raw[:8].isdigit() else ""


def _latest(rows: list[dict[str, Any]], *date_names: str) -> dict[str, Any]:
    if not rows:
        return {}
    return max(
        rows,
        key=lambda row: tuple(_date_key(row.get(name)) for name in date_names),
    )


def _latest_with_number(
    rows: list[dict[str, Any]],
    value_names: tuple[str, ...],
    *date_names: str,
) -> dict[str, Any]:
    usable = [row for row in rows if _number(_first(row, *value_names)) is not None]
    return _latest(usable, *date_names)


def _quarter_key(value: Any) -> tuple[int, int]:
    raw = str(value or "").strip().lower()
    if raw.startswith("fy"):
        raw = raw[2:]
    if len(raw) == 6 and raw[:4].isdigit() and raw[4] == "q" and raw[5] in "1234":
        return int(raw[:4]), int(raw[5])
    return (0, 0)


def _market(bundle: MarketDataBundle) -> str:
    if bundle.symbol.endswith(".HK"):
        return "hk"
    if bundle.symbol.endswith((".SH", ".SZ")):
        return "cn"
    return "us"


def _latest_finance_rows(
    records: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Return latest financial row, same-quarter prior year, and its source."""

    reports = records.get("financial_reports", [])
    candidates = [
        row
        for row in reports
        if _quarter_key(_first(row, "quarter", "fy_period")) != (0, 0)
    ]
    if candidates:
        current = max(
            candidates,
            key=lambda row: (
                _quarter_key(_first(row, "quarter", "fy_period")),
                _date_key(row.get("date")),
            ),
        )
        year, quarter = _quarter_key(_first(current, "quarter", "fy_period"))
        previous = next(
            (
                row
                for row in candidates
                if _quarter_key(_first(row, "quarter", "fy_period"))
                == (year - 1, quarter)
            ),
            {},
        )
        return current, previous, "financial_reports"

    performance = records.get("financial_performance", [])
    return (
        _latest(performance, "end_date", "info_date", "date"),
        {},
        "financial_performance",
    )


def _growth_pct(current: Any, previous: Any) -> float | None:
    current_number = _number(current)
    previous_number = _number(previous)
    if current_number is None or previous_number in (None, 0):
        return None
    return (current_number / previous_number - 1.0) * 100.0


def _hashes(bundle: MarketDataBundle, *names: str) -> list[str]:
    return sorted(
        {
            bundle.datasets[name].sha256
            for name in names
            if name in bundle.datasets
        }
    )


def _insufficient(
    skill_id: str,
    bundle: MarketDataBundle,
    warning: str,
    *datasets: str,
) -> SkillResult:
    return SkillResult(
        skill_id=skill_id,
        mode=bundle.mode,
        status="insufficient-evidence",
        duration_ms=0,
        dataset_hashes=_hashes(bundle, *datasets),
        warnings=[warning],
    )


def _result(
    skill_id: str,
    bundle: MarketDataBundle,
    summary: str,
    metrics: dict[str, Any],
    datasets: list[str],
    assumptions: list[str] | None = None,
    started: float | None = None,
    direction: str | None = None,
    confidence: int | None = None,
) -> SkillResult:
    published_metrics = dict(metrics)
    if direction:
        published_metrics["direction"] = direction
    if confidence is not None:
        published_metrics["confidence"] = max(0, min(100, int(confidence)))
    return SkillResult(
        skill_id=skill_id,
        mode=bundle.mode,
        status="success",
        duration_ms=(
            round((time.perf_counter() - started) * 1000)
            if started is not None
            else 0
        ),
        dataset_hashes=_hashes(bundle, *datasets),
        assumptions=list(assumptions or []),
        metrics=published_metrics,
        findings=[SkillFinding(summary, datasets, 0.8)],
    )


def _industry_name(records: dict[str, list[dict[str, Any]]]) -> str:
    row = _latest(records.get("industry", []), "date")
    if not row:
        row = _latest(records.get("industry_median", []), "date")
    if not row:
        row = _latest(records.get("stock_detail", []), "date", "listed_date")
    value = _first(
        row,
        "industry_name",
        "parent_l1_name",
        "parent_name",
        "industry_group",
        "business_sector",
        "economic_sector",
    )
    return str(value or "").strip()


def _is_financial_industry(records: dict[str, list[dict[str, Any]]]) -> bool:
    name = _industry_name(records)
    return any(token in name for token in ("金融", "银行", "保险", "证券"))


def _company_profile(
    bundle: MarketDataBundle,
    records: dict[str, list[dict[str, Any]]],
) -> SkillResult:
    started = time.perf_counter()
    detail = _latest(records.get("stock_detail", []), "date", "list_date")
    nature = _latest(records.get("equity_nature", []), "date")
    industry = _latest(records.get("industry", []), "date")
    industry_median = _latest(records.get("industry_median", []), "date")
    statuses = records.get("status_change", [])
    metrics: dict[str, Any] = {}
    for key, names in {
        "company_name": ("cn_name", "name", "stock_name", "short_name", "local_name"),
        "company_full_name": ("full_name", "company_name"),
        "list_date": ("list_date", "listed_date", "listing_date"),
        "industry": (
            "industry_name",
            "parent_l1_name",
            "industry_group",
            "business_sector",
            "economic_sector",
        ),
        "industry_code": ("industry_code", "parent_l1_code"),
        "company_nature": ("company_nature", "nature"),
    }.items():
        if key.startswith("industry"):
            source = industry or industry_median or detail
        else:
            source = nature if key == "company_nature" else detail
        value = _first(source, *names)
        if value not in (None, ""):
            metrics[key] = str(value)
    market = _market(bundle)
    metrics["market"] = market
    metrics["market_label"] = {"cn": "A股", "hk": "港股", "us": "美股"}[market]
    status = _first(detail, "status")
    if status not in (None, ""):
        metrics["listing_status"] = int(status)
    metrics["status_event_count"] = len(statuses)
    if not metrics.get("company_name") and not metrics.get("industry"):
        return _insufficient(
            COMPANY_PROFILE_ID,
            bundle,
            "company identity and industry context unavailable",
            "stock_detail",
            "industry",
            "equity_nature",
        )
    parts = [str(metrics.get("company_name") or bundle.symbol)]
    if metrics.get("industry"):
        parts.append(f"所属{metrics['industry']}")
    if metrics.get("company_nature"):
        parts.append(f"企业性质为{metrics['company_nature']}")
    if statuses:
        parts.append(f"研究期内记录到 {len(statuses)} 条特殊状态变更")
    elif market == "cn":
        parts.append("研究期内未返回特殊状态变更记录")
    elif metrics.get("listing_status") == 1:
        parts.append("基础信息显示当前处于在市状态")
    return _result(
        COMPANY_PROFILE_ID,
        bundle,
        "公司画像：" + "，".join(parts) + "。",
        metrics,
        [name for name in ("stock_detail", "industry", "industry_median", "equity_nature", "status_change") if name in bundle.datasets],
        ["公司介绍与企业性质来自公开基础信息，不等同于经营质量评价。"],
        started,
        "neutral",
        85,
    )


def _fundamental_profile(
    bundle: MarketDataBundle,
    records: dict[str, list[dict[str, Any]]],
) -> SkillResult:
    started = time.perf_counter()
    row, previous, source = _latest_finance_rows(records)
    if not row:
        return _insufficient(
            FUNDAMENTAL_PROFILE_ID,
            bundle,
            "quarterly financial report unavailable",
            "financial_reports",
            "financial_performance",
        )

    aliases = {
        "revenue": (
            "is_total_revenue",
            "is_revenue",
            "is_revenue_business_total",
            "is_sales_goods_services_net",
            "is_reported_revenue",
            "operating_revenue",
        ),
        "revenue_yoy_pct": ("operating_revenue_yoy",),
        "premium_income_cny": ("is_prem_income",),
        "net_profit": (
            "is_n_income_attr_p",
            "net_profit_parent",
            "is_n_income",
            "is_net_income",
            "is_net_income_after_tax",
            "is_reported_net_income",
        ),
        "net_profit_yoy_pct": ("net_profit_parent_yoy",),
        "adjusted_profit_yoy_pct": ("net_profit_excluding_nonrecurring_yoy",),
        "operating_cash_flow": (
            "cfs_net_cash_operating",
            "cfs_net_cf_operating",
            "cfs_reported_cf_operating",
            "net_cash_flow_operating",
        ),
        "operating_cash_flow_yoy_pct": ("net_cash_flow_operating_yoy",),
        "roe_pct": ("roe_weighted", "roe_diluted"),
        "equity": (
            "equity_parent",
            "equity_parent_common",
            "bs_common_equity_parent",
            "bs_common_equity_total",
            "bs_reported_equity",
        ),
        "basic_eps": (
            "is_basic_eps",
            "is_basic_eps_inc_exord",
            "is_eps_basic_inc_exord",
            "is_eps_basic_excl_exord",
            "basic_eps",
            "eps_weighted",
        ),
        "book_value_per_share": ("bvps",),
        "total_assets": ("bs_total_assets", "bs_reported_total_assets"),
        "total_liabilities": (
            "bs_total_liab",
            "bs_total_liabilities",
            "bs_reported_total_liabilities",
        ),
    }
    metrics: dict[str, Any] = {}
    quarter = str(_first(row, "quarter", "fy_period") or "").upper()
    period = quarter or _date_key(_first(row, "end_date", "date"))
    if period:
        metrics["reporting_period"] = period
    currency = str(_first(row, "currency") or "").strip()
    if currency:
        metrics["currency"] = currency
    for key, names in aliases.items():
        value = _number(_first(row, *names))
        if value is not None:
            metrics[key] = round(value, 4)

    if source == "financial_reports":
        comparisons = {
            "revenue_yoy_pct": (
                _first(
                    row,
                    "is_total_revenue",
                    "is_revenue",
                    "is_revenue_business_total",
                    "is_sales_goods_services_net",
                    "is_reported_revenue",
                ),
                _first(
                    previous,
                    "is_total_revenue",
                    "is_revenue",
                    "is_revenue_business_total",
                    "is_sales_goods_services_net",
                    "is_reported_revenue",
                ),
            ),
            "premium_income_yoy_pct": (
                _first(row, "is_prem_income"),
                _first(previous, "is_prem_income"),
            ),
            "net_profit_yoy_pct": (
                _first(
                    row,
                    "is_n_income_attr_p",
                    "is_n_income",
                    "is_net_income",
                    "is_net_income_after_tax",
                ),
                _first(
                    previous,
                    "is_n_income_attr_p",
                    "is_n_income",
                    "is_net_income",
                    "is_net_income_after_tax",
                ),
            ),
            "operating_cash_flow_yoy_pct": (
                _first(row, "cfs_net_cash_operating", "cfs_net_cf_operating"),
                _first(previous, "cfs_net_cash_operating", "cfs_net_cf_operating"),
            ),
        }
        for key, values in comparisons.items():
            growth = _growth_pct(*values)
            if growth is not None:
                metrics[key] = round(growth, 2)

        assets = metrics.get("total_assets")
        liabilities = metrics.get("total_liabilities")
        if assets not in (None, 0) and liabilities is not None:
            equity = assets - liabilities
            metrics.setdefault("equity", round(equity, 2))
            metrics["liability_to_assets_pct"] = round(liabilities / assets * 100.0, 2)

        fraction = _annualization_fraction(period)
        profit = metrics.get("net_profit")
        equity = metrics.get("equity")
        previous_assets = _number(
            _first(previous, "bs_total_assets", "bs_reported_total_assets")
        )
        previous_liabilities = _number(
            _first(
                previous,
                "bs_total_liab",
                "bs_total_liabilities",
                "bs_reported_total_liabilities",
            )
        )
        previous_equity = (
            previous_assets - previous_liabilities
            if previous_assets is not None and previous_liabilities is not None
            else None
        )
        average_equity = (
            (equity + previous_equity) / 2.0
            if equity is not None and previous_equity is not None
            else equity
        )
        if profit is not None and fraction and average_equity not in (None, 0):
            metrics["roe_pct"] = round(profit / fraction / average_equity * 100.0, 2)

    profit = metrics.get("net_profit")
    cash_flow = metrics.get("operating_cash_flow")
    financial_industry = _is_financial_industry(records)
    if not financial_industry and profit not in (None, 0) and cash_flow is not None:
        metrics["cash_to_profit_ratio"] = round(cash_flow / profit, 3)

    visible = [key for key in metrics if key != "reporting_period"]
    if not visible:
        return _insufficient(
            FUNDAMENTAL_PROFILE_ID,
            bundle,
            "financial performance fields unavailable",
            "financial_reports",
            "financial_performance",
        )

    parts = []
    if "revenue_yoy_pct" in metrics:
        parts.append(f"营收同比 {metrics['revenue_yoy_pct']:.2f}%")
    if "net_profit_yoy_pct" in metrics:
        parts.append(f"归母净利润同比 {metrics['net_profit_yoy_pct']:.2f}%")
    if "premium_income_yoy_pct" in metrics:
        parts.append(f"保险业务收入同比 {metrics['premium_income_yoy_pct']:.2f}%")
    if "adjusted_profit_yoy_pct" in metrics:
        parts.append(f"扣非净利润同比 {metrics['adjusted_profit_yoy_pct']:.2f}%")
    if "roe_pct" in metrics:
        parts.append(f"ROE {metrics['roe_pct']:.2f}%")
    if "cash_to_profit_ratio" in metrics:
        parts.append(f"经营现金流/归母净利润 {metrics['cash_to_profit_ratio']:.2f}")
    elif "operating_cash_flow_yoy_pct" in metrics:
        parts.append(f"经营现金流同比 {metrics['operating_cash_flow_yoy_pct']:.2f}%")
    growth_signals = [
        metrics[key]
        for key in ("revenue_yoy_pct", "net_profit_yoy_pct")
        if key in metrics
    ]
    if growth_signals and all(value > 5 for value in growth_signals):
        direction = "positive"
    elif growth_signals and all(value < 0 for value in growth_signals):
        direction = "negative"
    else:
        direction = "neutral"
    label = "、".join(parts) or "已取得最新财务报表核心字段"
    assumptions = (
        [
            "同比由最新季度与上年同季度累计口径计算。",
            "ROE 为累计归母净利润简单年化后除以可得平均总权益的估算值。",
        ]
        if source == "financial_reports"
        else ["业绩快报只作为季度财报不可用时的补充来源。"]
    )
    if financial_industry:
        assumptions.append(
            "金融企业经营现金流与工业企业口径不同，不使用现金流/利润倍数判断盈利质量。"
        )
    return _result(
        FUNDAMENTAL_PROFILE_ID,
        bundle,
        f"最新可用财务表现（{period or '报告期未知'}）：{label}。",
        metrics,
        [source],
        assumptions,
        started,
        direction,
        85 if len(growth_signals) >= 2 else 65,
    )


def _annualization_fraction(period: str) -> float | None:
    normalized = period.strip().upper()
    if normalized.startswith("FY"):
        normalized = normalized[2:]
    if len(normalized) == 6 and normalized[:4].isdigit() and normalized[4] == "Q":
        return {"1": 0.25, "2": 0.5, "3": 0.75, "4": 1.0}.get(normalized[5])
    if len(normalized) != 8:
        return None
    month_day = normalized[4:8]
    return {
        "0331": 0.25,
        "0630": 0.5,
        "0930": 0.75,
        "1231": 1.0,
    }.get(month_day)


def _valuation_profile(
    bundle: MarketDataBundle,
    records: dict[str, list[dict[str, Any]]],
) -> SkillResult:
    started = time.perf_counter()
    finance, _, finance_source = _latest_finance_rows(records)
    factor = _latest(records.get("factor", []), "date", "trade_date")
    price_volume = _latest(records.get("price_volume", []), "pv_market_cap_date", "date")
    market_financial_rows = records.get("market_financial", [])
    daily = _price_rows(records)
    last_price = _number(_first(daily[-1], "close", "adj_close", "close_price")) if daily else None
    market_cap = _number(_first(factor, "market_cap", "total_market_cap"))
    if market_cap is None:
        market_cap = _number(_first(price_volume, "pv_market_cap"))
    net_profit = _number(
        _first(
            finance,
            "is_n_income_attr_p",
            "net_profit_parent",
            "is_n_income",
            "is_net_income",
            "is_net_income_after_tax",
        )
    )
    equity = _number(
        _first(
            finance,
            "equity_parent",
            "equity_parent_common",
            "bs_common_equity_parent",
            "bs_common_equity_total",
            "bs_reported_equity",
        )
    )
    if equity is None:
        assets = _number(_first(finance, "bs_total_assets", "bs_reported_total_assets"))
        liabilities = _number(
            _first(
                finance,
                "bs_total_liab",
                "bs_total_liabilities",
                "bs_reported_total_liabilities",
            )
        )
        if assets is not None and liabilities is not None:
            equity = assets - liabilities
    eps = _number(
        _first(
            finance,
            "is_basic_eps",
            "is_basic_eps_inc_exord",
            "is_eps_basic_inc_exord",
            "is_eps_basic_excl_exord",
            "basic_eps",
            "eps_weighted",
        )
    )
    bvps = _number(_first(finance, "bvps"))
    period = str(_first(finance, "quarter", "fy_period") or "").upper() or _date_key(
        _first(finance, "end_date", "date")
    )
    fraction = _annualization_fraction(period)

    metrics: dict[str, Any] = {}
    assumptions = [
        "估值为最新行情与最近披露财务数据的快照，不包含同行或历史分位比较。"
    ]
    if last_price is not None:
        metrics["last_price"] = round(last_price, 4)
    if market_cap is not None:
        metrics["market_cap"] = round(market_cap, 2)
        currency = str(_first(price_volume, "pv_market_cap_currency") or "CNY").strip()
        metrics["market_cap_currency"] = currency
    if period:
        metrics["valuation_financial_period"] = period

    annualized_profit = None
    if net_profit is not None and fraction:
        annualized_profit = net_profit / fraction
        assumptions.append("PE 使用报告期累计归母净利润作简单年化，不是盈利预测。")
    pe_row = _latest_with_number(
        market_financial_rows,
        (
            "curr_pe_dil_excl_ttm",
            "curr_pe_dil_excl_issue_ttm",
            "curr_pe_basic_excl_ttm",
        ),
        "date",
        "period_end_date",
    )
    direct_pe = _number(
        _first(
            pe_row,
            "curr_pe_dil_excl_ttm",
            "curr_pe_dil_excl_issue_ttm",
            "curr_pe_basic_excl_ttm",
        )
    )
    pb_row = _latest_with_number(
        market_financial_rows,
        ("curr_pb", "curr_pb_issue", "curr_pb_lfy", "curr_pb_issue_lfy"),
        "date",
        "period_end_date",
    )
    direct_pb = _number(
        _first(pb_row, "curr_pb", "curr_pb_issue", "curr_pb_lfy", "curr_pb_issue_lfy")
    )
    if direct_pe is not None and direct_pe > 0:
        metrics["pe_estimate"] = round(direct_pe, 2)
        assumptions.append("PE 优先采用 PandaData 最新可用市场财务统计口径。")
    elif annualized_profit is not None and annualized_profit > 0 and market_cap:
        metrics["pe_estimate"] = round(market_cap / annualized_profit, 2)
    elif eps is not None and eps > 0 and last_price is not None and fraction:
        metrics["pe_estimate"] = round(last_price / (eps / fraction), 2)
    elif net_profit is not None and net_profit <= 0:
        metrics["pe_meaningful"] = False

    if direct_pb is not None and direct_pb > 0:
        metrics["pb_estimate"] = round(direct_pb, 2)
    elif equity is not None and equity > 0 and market_cap:
        metrics["pb_estimate"] = round(market_cap / equity, 2)
    elif bvps is not None and bvps > 0 and last_price is not None:
        metrics["pb_estimate"] = round(last_price / bvps, 2)

    index_indicator = _latest(records.get("index_indicator", []), "date")
    index_pe = _number(_first(index_indicator, "pe_ttm", "pe_lyr"))
    index_pb = _number(_first(index_indicator, "pb_lf", "pb_ttm", "pb_lyr"))
    if index_pe is not None:
        metrics["csi300_pe_ttm"] = round(index_pe, 2)
    if index_pb is not None:
        metrics["csi300_pb_lf"] = round(index_pb, 2)

    industry_median_rows = records.get("industry_median", [])
    median_pe_row = _latest_with_number(
        industry_median_rows,
        ("imed_pe_ttm", "imed_pe_excl_exord_ttm"),
        "date",
    )
    median_pb_row = _latest_with_number(
        industry_median_rows,
        ("imed_pb_ttm", "imed_pb_fye_mid", "imed_pb_fye"),
        "date",
    )
    industry_pe = _number(_first(median_pe_row, "imed_pe_ttm", "imed_pe_excl_exord_ttm"))
    industry_pb = _number(_first(median_pb_row, "imed_pb_ttm", "imed_pb_fye_mid", "imed_pb_fye"))
    if industry_pe is not None:
        metrics["industry_median_pe_ttm"] = round(industry_pe, 2)
    if industry_pb is not None:
        metrics["industry_median_pb"] = round(industry_pb, 2)

    if not any(key in metrics for key in ("pe_estimate", "pb_estimate", "pe_meaningful")):
        return _insufficient(
            VALUATION_PROFILE_ID,
            bundle,
            "valuation inputs unavailable",
            "daily_pre",
            "daily",
            "factor",
            "financial_reports",
            "financial_performance",
        )

    parts = []
    if "pe_estimate" in metrics:
        parts.append(f"简单年化 PE 约 {metrics['pe_estimate']:.2f} 倍")
    elif metrics.get("pe_meaningful") is False:
        parts.append("最近披露利润非正，PE 不具备常规解释意义")
    if "pb_estimate" in metrics:
        parts.append(f"PB 约 {metrics['pb_estimate']:.2f} 倍")
    if "csi300_pe_ttm" in metrics or "csi300_pb_lf" in metrics:
        index_parts = []
        if "csi300_pe_ttm" in metrics:
            index_parts.append(f"PE-TTM {metrics['csi300_pe_ttm']:.2f} 倍")
        if "csi300_pb_lf" in metrics:
            index_parts.append(f"PB-LF {metrics['csi300_pb_lf']:.2f} 倍")
        parts.append("同期沪深300 " + "、".join(index_parts))
    if "industry_median_pe_ttm" in metrics or "industry_median_pb" in metrics:
        median_parts = []
        if "industry_median_pe_ttm" in metrics:
            median_parts.append(f"PE-TTM {metrics['industry_median_pe_ttm']:.2f} 倍")
        if "industry_median_pb" in metrics:
            median_parts.append(f"PB {metrics['industry_median_pb']:.2f} 倍")
        parts.append("同行中位数 " + "、".join(median_parts))
    return _result(
        VALUATION_PROFILE_ID,
        bundle,
        f"估值快照：{'、'.join(parts)}；缺少同行与历史分位时，不能单独判定贵或便宜。",
        metrics,
        [
            name
            for name in (
                "daily_pre",
                "daily",
                "factor",
                "index_indicator",
                "price_volume",
                "market_financial",
                "industry_median",
                finance_source,
            )
            if name in bundle.datasets
        ],
        assumptions,
        started,
        "neutral",
        70,
    )


def _price_rows(records: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = records.get("daily_pre") or records.get("daily") or []
    return sorted(rows, key=lambda row: _date_key(_first(row, "date", "trade_date")))


def _closes(rows: list[dict[str, Any]]) -> list[float]:
    values = []
    for row in rows:
        value = _number(_first(row, "alt_close", "adj_close", "close", "close_price"))
        if value is not None and value > 0:
            values.append(value)
    return values


def _period_return(values: list[float], days: int) -> float | None:
    if len(values) <= days or values[-days - 1] == 0:
        return None
    return (values[-1] / values[-days - 1] - 1.0) * 100.0


def _max_drawdown(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1.0)
    return worst * 100.0


def _annualized_volatility(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    returns = [
        values[index] / values[index - 1] - 1.0
        for index in range(1, len(values))
        if values[index - 1] != 0
    ]
    if len(returns) < 2:
        return None
    return statistics.pstdev(returns) * math.sqrt(252.0) * 100.0


def _market_profile(
    bundle: MarketDataBundle,
    records: dict[str, list[dict[str, Any]]],
) -> SkillResult:
    started = time.perf_counter()
    rows = _price_rows(records)
    values = _closes(rows)
    if len(values) < 21:
        return _insufficient(
            MARKET_PROFILE_ID,
            bundle,
            "at least 21 adjusted daily closes required",
            "daily_pre",
            "daily",
        )

    metrics: dict[str, Any] = {"observations": len(values)}
    for days in (20, 60, 120):
        value = _period_return(values, days)
        if value is not None:
            metrics[f"return_{days}d_pct"] = round(value, 2)
    volatility = _annualized_volatility(values[-61:])
    if volatility is not None:
        metrics["volatility_60d_ann_pct"] = round(volatility, 2)
    drawdown = _max_drawdown(values[-121:])
    if drawdown is not None:
        metrics["max_drawdown_120d_pct"] = round(drawdown, 2)
    recent = values[-252:]
    low, high = min(recent), max(recent)
    if high > low:
        metrics["range_position_252d_pct"] = round(
            (values[-1] - low) / (high - low) * 100.0,
            2,
        )

    index_values = _closes(
        sorted(
            records.get("index_daily", []),
            key=lambda row: _date_key(_first(row, "date", "trade_date")),
        )
    )
    stock_60d = _period_return(values, 60)
    index_60d = _period_return(index_values, 60)
    if stock_60d is not None and index_60d is not None:
        metrics["relative_to_csi300_60d_pct"] = round(stock_60d - index_60d, 2)

    price_volume = _latest(records.get("price_volume", []), "pv_market_cap_date", "date")
    foreign_relative = _number(_first(price_volume, "pv_rel_return_13w"))
    if foreign_relative is not None:
        metrics["relative_to_benchmark_13w_pct"] = round(foreign_relative, 2)

    industry = _latest(records.get("industry", []), "date")
    if not industry:
        industry = _latest(records.get("industry_median", []), "date")
    if not industry:
        industry = _latest(records.get("stock_detail", []), "listed_date")
    industry_name = _first(
        industry,
        "industry_name",
        "parent_l1_name",
        "parent_name",
        "industry_group",
        "business_sector",
        "economic_sector",
    )
    if industry_name:
        metrics["industry"] = str(industry_name)

    parts = []
    if "return_20d_pct" in metrics:
        parts.append(f"近20日 {metrics['return_20d_pct']:.2f}%")
    if "return_60d_pct" in metrics:
        parts.append(f"近60日 {metrics['return_60d_pct']:.2f}%")
    if "volatility_60d_ann_pct" in metrics:
        parts.append(f"60日年化波动 {metrics['volatility_60d_ann_pct']:.2f}%")
    if "max_drawdown_120d_pct" in metrics:
        parts.append(f"近120日最大回撤 {metrics['max_drawdown_120d_pct']:.2f}%")
    if "relative_to_csi300_60d_pct" in metrics:
        parts.append(
            f"相对沪深300近60日 {metrics['relative_to_csi300_60d_pct']:.2f} 个百分点"
        )
    if "relative_to_benchmark_13w_pct" in metrics:
        parts.append(
            "相对市场默认基准近13周 "
            f"{metrics['relative_to_benchmark_13w_pct']:.2f} 个百分点"
        )
    if industry_name:
        parts.append(f"所属行业 {industry_name}")
    relative = metrics.get(
        "relative_to_csi300_60d_pct",
        metrics.get("relative_to_benchmark_13w_pct"),
    )
    recent_return = metrics.get("return_60d_pct")
    if relative is not None and recent_return is not None:
        if relative > 5 and recent_return > 0:
            direction = "positive"
        elif relative < -5 and recent_return < 0:
            direction = "negative"
        else:
            direction = "neutral"
    else:
        direction = "neutral"
    assumptions = ["收益、波动和回撤均由历史收盘价计算，不构成预测信号。"]
    if _market(bundle) != "cn":
        assumptions.append(
            "港美股相对收益使用 PandaData 价量指标中的默认市场基准，不能替代自定义基准回测。"
        )
    return _result(
        MARKET_PROFILE_ID,
        bundle,
        f"市场表现：{'、'.join(parts)}。历史表现只描述当前状态，不代表未来方向。",
        metrics,
        [name for name in ("daily_pre", "daily", "index_daily", "industry", "industry_median", "price_volume", "stock_detail") if name in bundle.datasets],
        assumptions,
        started,
        direction,
        80,
    )


def _percentile(values: list[float], target: float) -> float | None:
    clean = sorted(value for value in values if math.isfinite(value))
    if len(clean) < 2:
        return None
    return sum(value <= target for value in clean) / len(clean) * 100.0


def _industry_profile(
    bundle: MarketDataBundle,
    records: dict[str, list[dict[str, Any]]],
) -> SkillResult:
    started = time.perf_counter()
    rows = records.get("industry_peer_factors", [])
    if not rows:
        median_rows = records.get("industry_median", [])
        if median_rows:
            median = _latest(median_rows, "date")
            metrics: dict[str, Any] = {
                "industry": str(_first(median, "industry_name") or "行业未知")
            }
            for output, names in {
                "industry_median_pe_ttm": ("imed_pe_ttm", "imed_pe_excl_exord_ttm"),
                "industry_median_pb": ("imed_pb_ttm", "imed_pb_fye_mid", "imed_pb_fye"),
                "industry_median_roe_pct": ("imed_roe_avg_common_ttm", "imed_pretax_roe_ratio_ttm"),
            }.items():
                row = _latest_with_number(median_rows, names, "date")
                value = _number(_first(row, *names))
                if value is not None:
                    metrics[output] = round(value, 2)
            pv = _latest(records.get("price_volume", []), "pv_market_cap_date", "date")
            relative = _number(_first(pv, "pv_rel_return_13w"))
            if relative is not None:
                metrics["relative_to_benchmark_13w_pct"] = round(relative, 2)
            parts = []
            if "industry_median_pe_ttm" in metrics:
                parts.append(f"行业 PE-TTM 中位数 {metrics['industry_median_pe_ttm']:.2f} 倍")
            if "industry_median_pb" in metrics:
                parts.append(f"行业 PB 中位数 {metrics['industry_median_pb']:.2f} 倍")
            if "industry_median_roe_pct" in metrics:
                parts.append(f"行业 ROE 中位数 {metrics['industry_median_roe_pct']:.2f}%")
            if relative is not None:
                parts.append(f"标的近13周相对默认基准 {relative:.2f} 个百分点")
            direction = (
                "positive" if relative is not None and relative > 5
                else "negative" if relative is not None and relative < -5
                else "neutral"
            )
            return _result(
                INDUSTRY_PROFILE_ID,
                bundle,
                f"行业比较（{metrics['industry']}）："
                + "、".join(parts or ["已取得行业统计中位数"])
                + "。",
                metrics,
                [name for name in ("industry_median", "price_volume", "market_financial") if name in bundle.datasets],
                ["港美股行业比较采用 PandaData 行业统计中位数与默认市场基准，不虚构未提供的同行样本。"],
                started,
                direction,
                75,
            )
        return _insufficient(
            INDUSTRY_PROFILE_ID,
            bundle,
            "industry peer market data unavailable",
            "industry_peers",
            "industry_peer_factors",
        )
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip()
        if symbol:
            by_symbol.setdefault(symbol, []).append(row)
    latest_metrics: dict[str, dict[str, float]] = {}
    for symbol, symbol_rows in by_symbol.items():
        ordered = sorted(symbol_rows, key=lambda row: _date_key(row.get("date")))
        closes = _closes(ordered)
        latest = ordered[-1]
        values: dict[str, float] = {}
        period_return = _period_return(closes, 60)
        if period_return is not None:
            values["return_60d_pct"] = period_return
        market_cap = _number(_first(latest, "market_cap", "total_market_cap"))
        if market_cap is not None:
            values["market_cap"] = market_cap
        turnovers = [
            value
            for row in ordered[-20:]
            if (value := _number(row.get("turnover"))) is not None
        ]
        if turnovers:
            values["turnover_20d_avg"] = statistics.fmean(turnovers)
        latest_metrics[symbol] = values
    target = latest_metrics.get(bundle.symbol, {})
    if not target:
        return _insufficient(
            INDUSTRY_PROFILE_ID,
            bundle,
            "target absent from industry peer factor sample",
            "industry_peers",
            "industry_peer_factors",
        )
    metrics: dict[str, Any] = {
        "industry": _industry_name(records),
        "peer_count": len(latest_metrics),
    }
    for key, output in (
        ("return_60d_pct", "return_60d_percentile"),
        ("market_cap", "market_cap_percentile"),
        ("turnover_20d_avg", "turnover_20d_percentile"),
    ):
        target_value = target.get(key)
        if target_value is None:
            continue
        percentile = _percentile(
            [item[key] for item in latest_metrics.values() if key in item],
            target_value,
        )
        if percentile is not None:
            metrics[output] = round(percentile, 2)
    return_percentile = metrics.get("return_60d_percentile")
    if return_percentile is not None and return_percentile >= 70:
        direction = "positive"
    elif return_percentile is not None and return_percentile <= 30:
        direction = "negative"
    else:
        direction = "neutral"
    parts = [f"同行样本 {len(latest_metrics)} 只"]
    if return_percentile is not None:
        parts.append(f"近60日收益位于约 {return_percentile:.0f}% 分位")
    if "market_cap_percentile" in metrics:
        parts.append(f"市值位于约 {metrics['market_cap_percentile']:.0f}% 分位")
    return _result(
        INDUSTRY_PROFILE_ID,
        bundle,
        f"行业比较（{metrics.get('industry') or '行业未知'}）：" + "、".join(parts) + "。",
        metrics,
        ["industry_peers", "industry_peer_factors"],
        ["行业分位只描述当前同行样本中的相对位置，不代表未来收益。"],
        started,
        direction,
        75,
    )


def _change_pct(first: float | None, last: float | None) -> float | None:
    if first in (None, 0) or last is None:
        return None
    return (last / first - 1.0) * 100.0


def _flow_profile(
    bundle: MarketDataBundle,
    records: dict[str, list[dict[str, Any]]],
) -> SkillResult:
    started = time.perf_counter()
    if _market(bundle) != "cn":
        daily = _price_rows(records)
        amounts: list[float] = []
        volumes: list[float] = []
        for row in daily:
            volume = _number(_first(row, "volume"))
            amount = _number(_first(row, "amount"))
            close = _number(_first(row, "close", "alt_close"))
            if amount is None and volume is not None and close is not None:
                amount = volume * close
            if amount is not None and amount > 0:
                amounts.append(amount)
            if volume is not None and volume > 0:
                volumes.append(volume)
        metrics: dict[str, Any] = {}
        if amounts:
            metrics["average_traded_value_20d"] = round(statistics.fmean(amounts[-20:]), 2)
            if len(amounts) >= 40:
                previous = statistics.fmean(amounts[-40:-20])
                current = statistics.fmean(amounts[-20:])
                change = _change_pct(previous, current)
                if change is not None:
                    metrics["traded_value_20d_change_pct"] = round(change, 2)
        if volumes:
            metrics["average_volume_20d"] = round(statistics.fmean(volumes[-20:]), 2)
        pv = _latest(records.get("price_volume", []), "pv_market_cap_date", "date")
        avg_value = _number(_first(pv, "pv_avg_val_3m"))
        if avg_value is not None:
            metrics["vendor_average_traded_value_3m"] = round(avg_value, 2)
        currency = str(
            _first(pv, "pv_market_cap_currency", "pv_close_currency") or ""
        ).strip()
        if currency:
            metrics["currency"] = currency
        if not metrics:
            return _insufficient(
                FLOW_PROFILE_ID,
                bundle,
                "price and volume data returned no usable trading observations",
                "daily",
                "price_volume",
            )
        parts = []
        if "average_traded_value_20d" in metrics:
            parts.append(
                f"近20日平均成交额约 {metrics['average_traded_value_20d']:.2f}"
                + (f" {currency}" if currency else "")
            )
        if "traded_value_20d_change_pct" in metrics:
            parts.append(f"近20日成交额较前20日变化 {metrics['traded_value_20d_change_pct']:.2f}%")
        return _result(
            FLOW_PROFILE_ID,
            bundle,
            "资金与交易活跃度：" + "、".join(parts or ["已取得成交量与成交额数据"]) + "。",
            metrics,
            [name for name in ("daily", "price_volume") if name in bundle.datasets],
            ["港美股缺少 A 股融资融券、北向资金和龙虎榜口径，因此只描述成交活跃度，不将其解释为净流入。"],
            started,
            "neutral",
            70,
        )
    metrics: dict[str, Any] = {}
    signals: list[float] = []
    margin_rows = sorted(records.get("margin", []), key=lambda row: _date_key(row.get("date")))
    if margin_rows:
        by_date: dict[str, float] = {}
        for row in margin_rows:
            date_key = _date_key(row.get("date"))
            balance = _number(_first(row, "margin_balance", "total_balance"))
            if date_key and balance is not None:
                by_date[date_key] = max(by_date.get(date_key, 0.0), balance)
        ordered = [value for _, value in sorted(by_date.items())]
        if ordered:
            metrics["margin_balance_latest"] = round(ordered[-1], 2)
            change = _change_pct(ordered[max(0, len(ordered) - 21)], ordered[-1])
            if change is not None:
                metrics["margin_balance_20d_change_pct"] = round(change, 2)
                signals.append(change)
    north_by_date: dict[str, float] = {}
    for row in records.get("northbound_holding", []):
        date_key = _date_key(row.get("date"))
        value = _number(_first(row, "holding_ratio", "adjusted_holding_ratio"))
        if date_key and value is not None:
            north_by_date[date_key] = value
    north_series = sorted(north_by_date.items())
    if north_series:
        latest_date, latest_value = north_series[-1]
        metrics["northbound_holding_ratio_latest_pct"] = round(latest_value, 4)
        metrics["northbound_holding_as_of"] = latest_date
        if len(north_series) > 1:
            baseline_index = max(0, len(north_series) - 21)
            baseline_date, baseline_value = north_series[baseline_index]
            gap_days = (
                datetime.strptime(latest_date, "%Y%m%d")
                - datetime.strptime(baseline_date, "%Y%m%d")
            ).days
            if gap_days <= 45:
                delta = latest_value - baseline_value
                metrics["northbound_holding_ratio_20d_change_pct_point"] = round(
                    delta,
                    4,
                )
            else:
                baseline_date, baseline_value = north_series[-2]
                gap_days = (
                    datetime.strptime(latest_date, "%Y%m%d")
                    - datetime.strptime(baseline_date, "%Y%m%d")
                ).days
                delta = latest_value - baseline_value
                metrics[
                    "northbound_holding_ratio_latest_report_change_pct_point"
                ] = round(delta, 4)
                metrics["northbound_change_interval_days"] = gap_days
            signals.append(delta * 10.0)
    block_rows = records.get("block_trade", [])
    if block_rows:
        metrics["block_trade_count"] = len(block_rows)
        metrics["block_trade_amount_cny"] = round(
            sum(_number(row.get("amount")) or 0.0 for row in block_rows),
            2,
        )
    lhb_rows = records.get("lhb_list", [])
    if lhb_rows:
        metrics["lhb_event_count"] = len(lhb_rows)
        metrics["lhb_reported_amount_cny"] = round(
            sum(_number(row.get("amount")) or 0.0 for row in lhb_rows),
            2,
        )
    if not metrics:
        return _insufficient(
            FLOW_PROFILE_ID,
            bundle,
            "capital-flow datasets returned no usable observations",
            "margin",
            "northbound_holding",
            "block_trade",
            "lhb_list",
        )
    score = sum(1 if value > 0 else -1 if value < 0 else 0 for value in signals)
    direction = "positive" if score > 0 else "negative" if score < 0 else "neutral"
    parts = []
    if "margin_balance_20d_change_pct" in metrics:
        parts.append(f"融资余额近20日变化 {metrics['margin_balance_20d_change_pct']:.2f}%")
    if "northbound_holding_ratio_20d_change_pct_point" in metrics:
        parts.append(
            "沪深股通持股比例近20日变化 "
            f"{metrics['northbound_holding_ratio_20d_change_pct_point']:.4f} 个百分点"
        )
    if "northbound_holding_ratio_latest_report_change_pct_point" in metrics:
        parts.append(
            "沪深股通持股比例最近两个披露点变化 "
            f"{metrics['northbound_holding_ratio_latest_report_change_pct_point']:.4f} "
            f"个百分点（间隔 {metrics['northbound_change_interval_days']} 天）"
        )
    if "lhb_event_count" in metrics:
        parts.append(f"研究期内龙虎榜记录 {metrics['lhb_event_count']} 条")
    if "block_trade_count" in metrics:
        parts.append(f"研究期内大宗交易 {metrics['block_trade_count']} 条")
    return _result(
        FLOW_PROFILE_ID,
        bundle,
        "资金与交易行为：" + "、".join(parts or ["已取得资金面数据"]) + "。",
        metrics,
        [name for name in ("margin", "northbound_holding", "block_trade", "lhb_list", "lhb_detail") if name in bundle.datasets],
        ["融资、北向、龙虎榜与大宗交易描述不同资金群体，不能合并成单一净流入结论。"],
        started,
        direction,
        70,
    )


def _as_of_rows(
    rows: list[dict[str, Any]],
    end_date: str,
    *date_names: str,
) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        candidates = [_date_key(row.get(name)) for name in date_names]
        known = [value for value in candidates if value]
        if not known or min(known) <= end_date:
            output.append(row)
    return output


def _ownership_profile(
    request: ResearchRequest,
    bundle: MarketDataBundle,
    records: dict[str, list[dict[str, Any]]],
) -> SkillResult:
    started = time.perf_counter()
    if request.market != "cn":
        metrics: dict[str, Any] = {}
        score = 0
        concentration = _latest(records.get("investor_concentration", []), "date", "info_date")
        total_investors = _number(_first(concentration, "total_investors"))
        concentration_ratio = _number(
            _first(concentration, "investor_outstanding_ratio")
        )
        if total_investors is not None:
            metrics["tracked_investor_count"] = round(total_investors)
        if concentration_ratio is not None:
            metrics["tracked_investor_outstanding_ratio_pct"] = round(
                concentration_ratio, 4
            )
        ranking = records.get("investor_ranking", [])
        if ranking:
            metrics["ranked_investor_count"] = len(ranking)
            latest_rank_date = max(
                (_date_key(row.get("info_date")) for row in ranking),
                default="",
            )
            if latest_rank_date:
                current = [
                    row
                    for row in ranking
                    if _date_key(row.get("info_date")) == latest_rank_date
                ]
                ratio = sum(
                    _number(row.get("investor_outstanding_ratio")) or 0.0
                    for row in current
                )
                metrics["ranked_investor_ratio_pct"] = round(ratio, 4)
        insider_rows = _as_of_rows(
            records.get("insider_transactions", []),
            request.end_date,
            "info_date",
            "transaction_date",
        )
        if insider_rows:
            net_shares = sum(
                _number(_first(row, "adjusted_trade_shares", "reported_trade_shares"))
                or 0.0
                for row in insider_rows
            )
            metrics["insider_transaction_count"] = len(insider_rows)
            metrics["insider_net_reported_shares"] = round(net_shares, 2)
            score += 1 if net_shares > 0 else -1 if net_shares < 0 else 0
        holdings = _as_of_rows(
            records.get("shareholder_holdings", []),
            request.end_date,
            "holding_date",
        )
        if holdings:
            latest_holding_date = max(
                (_date_key(row.get("holding_date")) for row in holdings),
                default="",
            )
            current = [
                row
                for row in holdings
                if _date_key(row.get("holding_date")) == latest_holding_date
            ]
            metrics["reported_shareholder_count"] = len(current)
            ratio = sum(
                _number(_first(row, "outstanding_ratio")) or 0.0
                for row in current
            )
            if ratio:
                metrics["reported_shareholder_ratio_pct"] = round(ratio, 4)
            net_change = sum(
                _number(_first(row, "sharehold_change")) or 0.0
                for row in current
            )
            metrics["reported_shareholding_net_change"] = round(net_change, 2)
            score += 1 if net_change > 0 else -1 if net_change < 0 else 0
        if not metrics:
            return _insufficient(
                OWNERSHIP_PROFILE_ID,
                bundle,
                "investor, insider and shareholder datasets returned no usable observations",
                "investor_concentration",
                "investor_ranking",
                "insider_transactions",
                "shareholder_holdings",
            )
        parts = []
        if "insider_transaction_count" in metrics:
            parts.append(
                f"研究期内内部人交易 {metrics['insider_transaction_count']} 条，"
                f"申报净变动 {metrics['insider_net_reported_shares']:.0f} 股"
            )
        if "reported_shareholder_count" in metrics:
            parts.append(f"最新披露持仓样本 {metrics['reported_shareholder_count']} 条")
        if "ranked_investor_count" in metrics:
            parts.append(f"投资者排行记录 {metrics['ranked_investor_count']} 条")
        direction = "positive" if score > 0 else "negative" if score < 0 else "neutral"
        return _result(
            OWNERSHIP_PROFILE_ID,
            bundle,
            "股东与内部人行为：" + "、".join(parts or ["已取得投资者结构数据"]) + "。",
            metrics,
            [name for name in ("investor_concentration", "top20_concentration", "investor_ranking", "insider_transactions", "shareholder_holdings") if name in bundle.datasets],
            ["内部人交易包含期权行权、转换和其他非公开市场买卖类型，净股数只作事实汇总，不能直接视为看多或看空信号。"],
            started,
            direction,
            75,
        )
    metrics: dict[str, Any] = {}
    score = 0
    holder_rows = sorted(
        _as_of_rows(records.get("holder_count", []), request.end_date, "date"),
        key=lambda row: (_date_key(row.get("end_date")), _date_key(row.get("date"))),
    )
    holder_values = [
        value
        for row in holder_rows
        if (value := _number(_first(row, "a_holders", "holders"))) is not None
    ]
    if holder_values:
        metrics["holder_count_latest"] = round(holder_values[-1])
        change = _change_pct(holder_values[-2] if len(holder_values) > 1 else None, holder_values[-1])
        if change is not None:
            metrics["holder_count_change_pct"] = round(change, 2)
    top_rows = _as_of_rows(records.get("top_holders", []), request.end_date, "date")
    if top_rows:
        latest_period = max(_date_key(row.get("end_date")) for row in top_rows)
        current = [row for row in top_rows if _date_key(row.get("end_date")) == latest_period]
        ratios = [_number(row.get("hold_percent_total")) for row in current]
        metrics["top_holders_total_ratio_pct"] = round(sum(value or 0.0 for value in ratios), 2)
    pledge_rows = _as_of_rows(records.get("stock_pledge", []), request.end_date, "publish_date")
    pledge_ratios = [
        value
        for row in pledge_rows
        if (value := _number(row.get("acc_pledge_total_ratio"))) is not None
    ]
    if pledge_ratios:
        metrics["max_acc_pledge_total_ratio_pct"] = round(max(pledge_ratios), 2)
        if max(pledge_ratios) >= 20:
            score -= 1
    changes = _as_of_rows(records.get("shareholder_change", []), request.end_date, "info_date")
    increases = sum("增" in str(row.get("direction") or "") for row in changes)
    decreases = sum("减" in str(row.get("direction") or "") for row in changes)
    if changes:
        metrics["shareholder_increase_plan_count"] = increases
        metrics["shareholder_decrease_plan_count"] = decreases
        score += 1 if increases > decreases else -1 if decreases > increases else 0
    repurchases = _as_of_rows(records.get("repurchase", []), request.end_date, "date", "announcement_dt")
    if repurchases:
        metrics["repurchase_record_count"] = len(repurchases)
        metrics["repurchase_value_cny"] = round(
            sum(_number(row.get("buy_back_value")) or 0.0 for row in repurchases),
            2,
        )
        score += 1
    releases = _as_of_rows(records.get("restricted_release", []), request.end_date, "date")
    upcoming = [row for row in releases if _date_key(row.get("relieve_date")) > request.end_date]
    if upcoming:
        metrics["upcoming_restricted_release_shares"] = round(
            sum(_number(row.get("relieve_shares")) or 0.0 for row in upcoming),
            2,
        )
        score -= 1
    placards = _as_of_rows(records.get("equity_placard", []), request.end_date, "info_date")
    if placards:
        metrics["equity_placard_count"] = len(placards)
    share_row = _latest(records.get("share_float", []), "date")
    total_shares = _number(_first(share_row, "total", "total_a"))
    if total_shares is not None:
        metrics["total_shares"] = round(total_shares, 2)
    if not metrics:
        return _insufficient(
            OWNERSHIP_PROFILE_ID,
            bundle,
            "ownership and capital-action datasets returned no usable observations",
            "holder_count",
            "top_holders",
            "stock_pledge",
            "shareholder_change",
            "repurchase",
            "restricted_release",
        )
    direction = "positive" if score > 0 else "negative" if score < 0 else "neutral"
    parts = []
    if "holder_count_change_pct" in metrics:
        holder_change = metrics["holder_count_change_pct"]
        concentration = (
            "持股趋于分散"
            if holder_change > 0
            else "持股趋于集中"
            if holder_change < 0
            else "集中度基本不变"
        )
        metrics["holder_concentration_signal"] = concentration
        parts.append(f"股东户数变化 {holder_change:.2f}%（{concentration}）")
    if "max_acc_pledge_total_ratio_pct" in metrics:
        parts.append(f"可见累计质押占总股本最高 {metrics['max_acc_pledge_total_ratio_pct']:.2f}%")
    if "shareholder_decrease_plan_count" in metrics:
        parts.append(
            f"增持计划 {metrics['shareholder_increase_plan_count']} 条、"
            f"减持计划 {metrics['shareholder_decrease_plan_count']} 条"
        )
    if "repurchase_record_count" in metrics:
        parts.append(f"回购记录 {metrics['repurchase_record_count']} 条")
    if "upcoming_restricted_release_shares" in metrics:
        parts.append(f"已公告待解禁股份 {metrics['upcoming_restricted_release_shares']:.0f} 股")
    return _result(
        OWNERSHIP_PROFILE_ID,
        bundle,
        "股东与资本行为：" + "、".join(parts or ["已取得股东结构数据"]) + "。",
        metrics,
        [name for name in ("holder_count", "top_holders", "stock_pledge", "shareholder_change", "equity_placard", "repurchase", "restricted_release", "share_float") if name in bundle.datasets],
        ["股东户数增减只表示持股集中度变化，不能单独解释为利好或利空。"],
        started,
        direction,
        75,
    )


def _audit_opinion_status(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    if not normalized:
        return "unknown"
    if normalized in {
        "no_audit_performed",
        "not_audited",
        "unaudited",
        "未经审计",
    }:
        return "not_audited"
    if normalized in {
        "unqualified_opinion",
        "standard_unqualified",
        "standard_unqualified_opinion",
        "unmodified_opinion",
        "clean_opinion",
        "无保留意见",
        "标准无保留意见",
    } or "无保留" in normalized:
        return "normal"
    if normalized in {
        "qualified_opinion",
        "adverse_opinion",
        "disclaimer_of_opinion",
        "unable_to_express_opinion",
        "保留意见",
        "否定意见",
        "无法表示意见",
    }:
        return "modified"
    return "unknown"


def _audit_opinion_label(value: Any) -> str:
    normalized = str(value or "").strip()
    status = _audit_opinion_status(normalized)
    if status == "normal":
        return "标准无保留审计意见"
    if status == "not_audited":
        return "未经审计"
    if status == "modified":
        labels = {
            "qualified_opinion": "保留意见",
            "adverse_opinion": "否定意见",
            "disclaimer_of_opinion": "无法表示意见",
            "unable_to_express_opinion": "无法表示意见",
        }
        return labels.get(normalized.lower(), normalized)
    return normalized or "未知"


def _deduplicate_rows(
    rows: list[dict[str, Any]],
    *fields: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        key = tuple(str(row.get(field) or "").strip() for field in fields)
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def _latest_dividend_plans(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_period: dict[str, dict[str, Any]] = {}
    for row in rows:
        period = str(row.get("quarter") or "").strip().lower()
        if not period:
            period = _date_key(row.get("announcement_date"))
        current = by_period.get(period)
        if current is None or _date_key(row.get("announcement_date")) >= _date_key(
            current.get("announcement_date")
        ):
            by_period[period] = row
    return list(by_period.values())


def _event_profile(
    request: ResearchRequest,
    bundle: MarketDataBundle,
    records: dict[str, list[dict[str, Any]]],
) -> SkillResult:
    started = time.perf_counter()
    if request.market != "cn":
        metrics: dict[str, Any] = {}
        score = 0
        recommendation = _latest(records.get("recommendation_consensus", []), "date")
        if recommendation:
            for output, names in {
                "analyst_strong_buy_count": ("strong_buy_num",),
                "analyst_buy_count": ("buy_num",),
                "analyst_hold_count": ("hold",),
                "analyst_sell_count": ("sell_num",),
                "analyst_strong_sell_count": ("strong_sell_num",),
                "analyst_recommendation_count": ("recommendations_num",),
                "analyst_recommendation_mean": ("mean",),
            }.items():
                value = _number(_first(recommendation, *names))
                if value is not None:
                    metrics[output] = round(value, 4)
            positive = metrics.get("analyst_strong_buy_count", 0) + metrics.get(
                "analyst_buy_count", 0
            )
            negative = metrics.get("analyst_sell_count", 0) + metrics.get(
                "analyst_strong_sell_count", 0
            )
            score += 1 if positive > negative else -1 if negative > positive else 0
        estimates = records.get("noncyclical_consensus", [])
        for row in estimates:
            indicator = str(row.get("indicator") or "").upper()
            mean = _number(row.get("mean"))
            if mean is None:
                continue
            if indicator == "TP":
                metrics["analyst_target_price_mean"] = round(mean, 4)
                metrics["analyst_target_price_currency"] = str(
                    row.get("currency") or ""
                )
                metrics["analyst_target_price_estimate_count"] = round(
                    _number(_first(row, "included_estimates_num", "estimates_num"))
                    or 0
                )
            elif indicator == "LTGROWTH":
                metrics["analyst_long_term_growth_mean"] = round(mean, 4)
        event_names = (
            "dividend_events",
            "market_events",
            "meeting_events",
            "financial_events",
            "ir_events",
        )
        for name in event_names:
            date_fields = (
                ("publish_date", "info_date", "start_date")
                if name == "dividend_events"
                else ("info_date", "start_date")
            )
            rows = _as_of_rows(records.get(name, []), request.end_date, *date_fields)
            if rows:
                metrics[f"{name}_count"] = len(rows)
        dividends = _as_of_rows(
            records.get("dividend_events", []),
            request.end_date,
            "publish_date",
        )
        if dividends:
            latest_dividend = _latest(dividends, "publish_date", "excute_date")
            amount = _number(_first(latest_dividend, "number"))
            if amount is not None:
                metrics["latest_dividend_per_share"] = round(amount, 4)
                metrics["latest_dividend_currency"] = str(
                    latest_dividend.get("currency") or ""
                )
        if not metrics:
            return _insufficient(
                EVENT_PROFILE_ID,
                bundle,
                "consensus and corporate-event datasets returned no usable observations",
                "recommendation_consensus",
                "noncyclical_consensus",
                *event_names,
            )
        parts = []
        if "analyst_recommendation_count" in metrics:
            parts.append(
                f"分析师建议样本 {metrics['analyst_recommendation_count']:.0f} 份，"
                f"其中强买/买入 {metrics.get('analyst_strong_buy_count', 0) + metrics.get('analyst_buy_count', 0):.0f} 份、"
                f"卖出/强卖 {metrics.get('analyst_sell_count', 0) + metrics.get('analyst_strong_sell_count', 0):.0f} 份"
            )
        if "financial_events_count" in metrics:
            parts.append(f"研究期内财务事件 {metrics['financial_events_count']} 条")
        if "ir_events_count" in metrics:
            parts.append(f"投资者关系事件 {metrics['ir_events_count']} 条")
        if "dividend_events_count" in metrics:
            parts.append(f"分红相关事件 {metrics['dividend_events_count']} 条")
        direction = "positive" if score > 0 else "negative" if score < 0 else "neutral"
        return _result(
            EVENT_PROFILE_ID,
            bundle,
            "一致预期与公司事件：" + "、".join(parts or ["已取得一致预期或公司事件数据"]) + "。",
            metrics,
            [name for name in ("recommendation_consensus", "noncyclical_consensus", *event_names) if name in bundle.datasets],
            ["分析师一致预期和目标价是第三方观点汇总，不是系统买卖建议，也不保证实现。"],
            started,
            direction,
            75,
        )
    metrics: dict[str, Any] = {}
    score = 0
    forecasts = _as_of_rows(records.get("financial_forecast", []), request.end_date, "info_date")
    forecast = _latest(forecasts, "info_date", "end_date")
    if forecast:
        forecast_type = _first(forecast, "forecast_type", "forecast_description")
        if forecast_type:
            metrics["forecast_type"] = str(forecast_type)
        floor = _number(forecast.get("forecast_growth_rate_floor"))
        ceiling = _number(forecast.get("forecast_growth_rate_ceiling"))
        if floor is not None:
            metrics["forecast_growth_floor_pct"] = round(floor, 2)
        if ceiling is not None:
            metrics["forecast_growth_ceiling_pct"] = round(ceiling, 2)
        midpoint = statistics.fmean([value for value in (floor, ceiling) if value is not None]) if any(value is not None for value in (floor, ceiling)) else None
        if midpoint is not None:
            score += 1 if midpoint > 0 else -1 if midpoint < 0 else 0
    opinions = _as_of_rows(records.get("audit_opinion", []), request.end_date, "date")
    audited_opinions = [
        row
        for row in opinions
        if _audit_opinion_status(_first(row, "opinion")) != "not_audited"
    ]
    opinion = _latest(audited_opinions or opinions, "date", "quarter")
    if opinion:
        text_value = str(_first(opinion, "opinion", "audit_type") or "")
        audit_status = _audit_opinion_status(text_value)
        metrics["audit_opinion"] = _audit_opinion_label(text_value)
        metrics["audit_opinion_status"] = audit_status
        if audit_status == "modified":
            score -= 1
    litigation = _as_of_rows(records.get("litigation", []), request.end_date, "info_date")
    if litigation:
        metrics["litigation_count"] = len(litigation)
        metrics["litigation_involved_amount_cny"] = round(
            sum(_number(row.get("involved_amount")) or 0.0 for row in litigation),
            2,
        )
        score -= 1
    illegal = _as_of_rows(records.get("equity_illegal", []), request.end_date, "info_date")
    if illegal:
        metrics["equity_illegal_count"] = len(illegal)
        score -= 1
    guarantee = _latest(
        _as_of_rows(records.get("guarantee", []), request.end_date, "info_date"),
        "info_date",
        "end_date",
    )
    ratio = _number(guarantee.get("total_amount_ratio")) if guarantee else None
    if ratio is not None:
        metrics["guarantee_to_net_assets_pct"] = round(ratio, 2)
        if ratio >= 50:
            score -= 1
    contracts = _as_of_rows(records.get("material_contract", []), request.end_date, "info_date")
    if contracts:
        metrics["material_contract_count"] = len(contracts)
    related = _deduplicate_rows(
        _as_of_rows(records.get("related_party", []), request.end_date, "info_date"),
        "info_date",
        "party_name",
        "trading_method",
        "amount",
    )
    if related:
        metrics["related_party_transaction_count"] = len(related)
    placements = _as_of_rows(records.get("private_placement", []), request.end_date, "announcement_date")
    allotments = _as_of_rows(records.get("allotment", []), request.end_date, "announcement_date")
    if placements:
        metrics["private_placement_count"] = len(placements)
    if allotments:
        metrics["allotment_count"] = len(allotments)
    dividends = _latest_dividend_plans(
        _as_of_rows(
            records.get("dividend_amount", []),
            request.end_date,
            "announcement_date",
        )
    )
    if dividends:
        metrics["dividend_plan_count"] = len(dividends)
        latest_dividend = _latest(dividends, "announcement_date", "quarter")
        latest_amount = _number(latest_dividend.get("total_div_amount"))
        if latest_amount is not None:
            metrics["latest_dividend_plan_amount_cny"] = round(latest_amount, 2)
        latest_quarter = str(latest_dividend.get("quarter") or "").upper()
        if latest_quarter:
            metrics["latest_dividend_plan_period"] = latest_quarter
    activities = _as_of_rows(records.get("investor_activity", []), request.end_date, "date")
    if activities:
        metrics["investor_activity_count"] = len(activities)
    if not metrics:
        return _insufficient(
            EVENT_PROFILE_ID,
            bundle,
            "no publishable forecast, governance or corporate-event observations",
            "financial_forecast",
            "audit_opinion",
            "litigation",
            "equity_illegal",
            "guarantee",
            "material_contract",
        )
    direction = "positive" if score > 0 else "negative" if score < 0 else "neutral"
    parts = []
    if "forecast_type" in metrics:
        parts.append(f"最新业绩预告类型为{metrics['forecast_type']}")
    if "audit_opinion" in metrics:
        parts.append(f"最新审计意见为{metrics['audit_opinion']}")
    if "litigation_count" in metrics:
        parts.append(f"研究期内诉讼/仲裁记录 {metrics['litigation_count']} 条")
    if "equity_illegal_count" in metrics:
        parts.append(f"股权违规记录 {metrics['equity_illegal_count']} 条")
    if "material_contract_count" in metrics:
        parts.append(f"重大合同记录 {metrics['material_contract_count']} 条")
    return _result(
        EVENT_PROFILE_ID,
        bundle,
        "预期、治理与公司事件：" + "、".join(parts or ["已取得公司事件数据"]) + "。",
        metrics,
        [name for name in ("financial_forecast", "audit_opinion", "litigation", "equity_illegal", "guarantee", "material_contract", "related_party", "private_placement", "allotment", "dividend_amount", "investor_activity") if name in bundle.datasets],
        [
            "公司公告、管理层交流和业绩预告属于已披露信息或管理层表述，不等同于结果已实现。",
            "分红按报告期保留最新公告阶段，避免把预案、决案和实施公告重复累加；关联交易记录数本身不构成负面判断。",
        ],
        started,
        direction,
        75,
    )


MACRO_LABELS = {
    "IR0004522": "10年期国债到期收益率",
    "IR0003622": "人民币贷款加权平均利率",
    "MB0000004": "M1同比",
    "MB0000006": "M2同比",
    "FS0000002": "金融业固定资产投资累计同比",
    "EE0017443": "电子信息制造业营业收入累计同比",
    "EP0000399": "动力电池产量当月同比",
    "EP0000400": "动力电池装车量累计同比",
    "FB0045844": "四川名酒批发价格指数",
    "FB0045846": "四川名酒批发价格指数旬环比",
}


def _macro_profile(
    request: ResearchRequest,
    bundle: MarketDataBundle,
    records: dict[str, list[dict[str, Any]]],
) -> SkillResult:
    started = time.perf_counter()
    metrics: dict[str, Any] = {}
    parts = []
    for dataset in ("macro_ir", "macro_mb", "macro_sector"):
        rows = _as_of_rows(records.get(dataset, []), request.end_date, "period_date", "date")
        by_symbol: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            symbol = str(row.get("symbol") or "").strip()
            if symbol:
                by_symbol.setdefault(symbol, []).append(row)
        for symbol, symbol_rows in by_symbol.items():
            latest = _latest(symbol_rows, "period_date", "date")
            value = _number(_first(latest, "data_value", "value"))
            if value is None:
                continue
            label = MACRO_LABELS.get(symbol, symbol)
            key = "macro_" + re_safe_key(symbol)
            metrics[key] = round(value, 4)
            parts.append(f"{label}最新值 {value:.4g}")
    if not metrics:
        return _insufficient(
            MACRO_PROFILE_ID,
            bundle,
            "curated macro indicators unavailable",
            "macro_ir",
            "macro_mb",
            "macro_sector",
        )
    return _result(
        MACRO_PROFILE_ID,
        bundle,
        "宏观环境快照：" + "、".join(parts[:6]) + "。",
        metrics,
        [name for name in ("macro_ir", "macro_mb", "macro_sector") if name in bundle.datasets],
        ["宏观指标只提供环境背景；没有明确传导证据时，不直接推导个股涨跌。"],
        started,
        "neutral",
        65,
    )


def re_safe_key(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "_" for character in value)


def _mock_profiles(
    request: ResearchRequest,
    bundle: MarketDataBundle,
) -> dict[str, SkillResult]:
    seed = stable_seed(request.symbol + "research")
    revenue_growth = round((seed % 3500) / 100.0 - 8.0, 2)
    profit_growth = round(((seed // 7) % 5000) / 100.0 - 18.0, 2)
    roe = round(4.0 + ((seed // 13) % 1800) / 100.0, 2)
    pe = round(7.0 + ((seed // 17) % 4000) / 100.0, 2)
    pb = round(0.7 + ((seed // 23) % 700) / 100.0, 2)
    bars = _mock_bars(request.symbol)
    values = bars.close
    market_metrics = {
        "observations": len(values),
        "return_20d_pct": round(_period_return(values, 20) or 0.0, 2),
        "return_60d_pct": round(_period_return(values, 60) or 0.0, 2),
        "volatility_60d_ann_pct": round(
            _annualized_volatility(values[-61:]) or 0.0,
            2,
        ),
        "max_drawdown_120d_pct": round(_max_drawdown(values[-121:]) or 0.0, 2),
    }
    warning = ["offline deterministic mock; not valid for public evidence"]
    hashes = bundle.dataset_hashes
    return {
        FUNDAMENTAL_PROFILE_ID: SkillResult(
            FUNDAMENTAL_PROFILE_ID,
            "mock",
            "success",
            0,
            hashes,
            metrics={
                "revenue_yoy_pct": revenue_growth,
                "net_profit_yoy_pct": profit_growth,
                "roe_pct": roe,
            },
            findings=[SkillFinding(
                f"离线模拟财务快照：营收同比 {revenue_growth:.2f}%，"
                f"归母净利润同比 {profit_growth:.2f}%，ROE {roe:.2f}%。",
                ["daily"],
                0.5,
            )],
            warnings=warning,
        ),
        VALUATION_PROFILE_ID: SkillResult(
            VALUATION_PROFILE_ID,
            "mock",
            "success",
            0,
            hashes,
            assumptions=["offline deterministic valuation mock"],
            metrics={"pe_estimate": pe, "pb_estimate": pb},
            findings=[SkillFinding(
                f"离线模拟估值快照：PE {pe:.2f} 倍，PB {pb:.2f} 倍。",
                ["daily"],
                0.5,
            )],
            warnings=warning,
        ),
        MARKET_PROFILE_ID: SkillResult(
            MARKET_PROFILE_ID,
            "mock",
            "success",
            0,
            hashes,
            assumptions=["offline deterministic price path"],
            metrics=market_metrics,
            findings=[SkillFinding(
                "离线模拟市场表现："
                f"近20日 {market_metrics['return_20d_pct']:.2f}%，"
                f"近60日 {market_metrics['return_60d_pct']:.2f}%，"
                f"60日年化波动 {market_metrics['volatility_60d_ann_pct']:.2f}%，"
                f"近120日最大回撤 {market_metrics['max_drawdown_120d_pct']:.2f}%。",
                ["daily"],
                0.5,
            )],
            warnings=warning,
        ),
    }
