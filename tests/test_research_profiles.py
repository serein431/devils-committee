from backend.research_request import ResearchRequest
from backend.skills import research
from backend.skills.contracts import DatasetArtifact, MarketDataBundle


def _artifact(name: str) -> DatasetArtifact:
    return DatasetArtifact(
        name=name,
        method=name,
        params={},
        path=f"/tmp/{name}.parquet",
        sha256=f"hash-{name}",
        rows=130,
        mode="cache",
        fetched_at="2026-07-26T00:00:00+00:00",
    )


def _request() -> ResearchRequest:
    return ResearchRequest(
        "601628.SH",
        "cn",
        "研究公司的盈利、估值和市场风险",
        "20250101",
        "20260724",
    )


def test_profiles_turn_panda_data_into_company_research(monkeypatch):
    names = (
        "daily_pre",
        "factor",
        "index_daily",
        "index_indicator",
        "financial_reports",
        "industry",
    )
    bundle = MarketDataBundle(
        "601628.SH",
        "success",
        "cache",
        {name: _artifact(name) for name in names},
    )
    rows = {
        "daily_pre": [
            {
                "date": f"2025{index // 28 + 1:02d}{index % 28 + 1:02d}",
                "close": 20.0 + index * 0.1,
            }
            for index in range(130)
        ],
        "index_daily": [
            {
                "date": f"2025{index // 28 + 1:02d}{index % 28 + 1:02d}",
                "close": 4000.0 + index * 2.0,
            }
            for index in range(130)
        ],
        "factor": [
            {"date": "20260724", "market_cap": 100_000_000_000.0}
        ],
        "index_indicator": [
            {
                "date": "20260724",
                "symbol": "000300.SH",
                "pe_ttm": 13.25,
                "pb_lf": 1.42,
            }
        ],
        "financial_reports": [
            {
                "quarter": "2024q3",
                "date": "20251030",
                "is_total_revenue": 70_000_000_000.0,
                "is_n_income_attr_p": 5_000_000_000.0,
                "cfs_net_cash_operating": 6_000_000_000.0,
                "bs_total_assets": 520_000_000_000.0,
                "bs_total_liab": 470_000_000_000.0,
                "is_basic_eps": 0.5,
            },
            {
                "quarter": "2025q3",
                "date": "20261030",
                "is_total_revenue": 80_000_000_000.0,
                "is_n_income_attr_p": 6_000_000_000.0,
                "cfs_net_cash_operating": 7_200_000_000.0,
                "bs_total_assets": 560_000_000_000.0,
                "bs_total_liab": 510_000_000_000.0,
                "is_basic_eps": 0.6,
            }
        ],
        "industry": [
            {"stock_symbol": "601628.SH", "industry_name": "非银金融"}
        ],
    }
    monkeypatch.setattr(
        research,
        "_read_records",
        lambda bundle, name: rows.get(name, []),
    )

    profiles = research.build_research_profiles(_request(), bundle)

    fundamental = profiles[research.FUNDAMENTAL_PROFILE_ID]
    assert fundamental.status == "success"
    assert fundamental.metrics["revenue_yoy_pct"] == 14.29
    assert fundamental.metrics["net_profit_yoy_pct"] == 20.0
    assert "cash_to_profit_ratio" not in fundamental.metrics
    assert fundamental.metrics["operating_cash_flow_yoy_pct"] == 20.0
    assert any("金融企业" in item for item in fundamental.assumptions)

    valuation = profiles[research.VALUATION_PROFILE_ID]
    assert valuation.status == "success"
    assert valuation.metrics["pe_estimate"] == 12.5
    assert valuation.metrics["pb_estimate"] == 2.0
    assert valuation.metrics["csi300_pe_ttm"] == 13.25
    assert valuation.metrics["csi300_pb_lf"] == 1.42
    assert any("简单年化" in item for item in valuation.assumptions)

    market = profiles[research.MARKET_PROFILE_ID]
    assert market.status == "success"
    assert market.metrics["return_60d_pct"] > 0
    assert market.metrics["relative_to_csi300_60d_pct"] > 0
    assert market.metrics["industry"] == "非银金融"


def test_extended_profiles_cover_peers_flows_ownership_events_and_macro(monkeypatch):
    names = (
        "stock_detail",
        "industry",
        "equity_nature",
        "industry_peers",
        "industry_peer_factors",
        "margin",
        "northbound_holding",
        "holder_count",
        "top_holders",
        "stock_pledge",
        "shareholder_change",
        "repurchase",
        "restricted_release",
        "share_float",
        "financial_forecast",
        "audit_opinion",
        "litigation",
        "material_contract",
        "macro_ir",
        "macro_mb",
    )
    bundle = MarketDataBundle(
        "601628.SH",
        "success",
        "cache",
        {name: _artifact(name) for name in names},
    )
    peer_rows = []
    for symbol, step in (("601628.SH", 0.20), ("601318.SH", 0.10), ("601601.SH", -0.02)):
        peer_rows.extend(
            {
                "date": f"2026{index // 28 + 1:02d}{index % 28 + 1:02d}",
                "symbol": symbol,
                "close": 20.0 + index * step,
                "market_cap": 100_000_000_000.0 + step * 1_000_000_000,
                "turnover": 0.3 + step,
            }
            for index in range(70)
        )
    rows = {
        "stock_detail": [{"symbol": "601628.SH", "name": "中国人寿"}],
        "industry": [{"stock_symbol": "601628.SH", "industry_code": "801790", "industry_name": "非银金融"}],
        "equity_nature": [{"symbol": "601628.SH", "company_nature": "中央国有企业"}],
        "industry_peers": [{"stock_symbol": symbol} for symbol in ("601628.SH", "601318.SH", "601601.SH")],
        "industry_peer_factors": peer_rows,
        "margin": [
            {"date": f"202607{index + 1:02d}", "margin_balance": 100.0 + index}
            for index in range(20)
        ],
        "northbound_holding": [
            {"date": f"202607{index + 1:02d}", "holding_ratio": 2.0 + index * 0.01}
            for index in range(20)
        ],
        "holder_count": [
            {"date": "20260430", "end_date": "20260331", "holders": 120_000},
            {"date": "20260720", "end_date": "20260630", "holders": 110_000},
        ],
        "top_holders": [
            {"date": "20260720", "end_date": "20260630", "hold_percent_total": 20.0},
            {"date": "20260720", "end_date": "20260630", "hold_percent_total": 15.0},
        ],
        "stock_pledge": [{"publish_date": "20260701", "acc_pledge_total_ratio": 3.0}],
        "shareholder_change": [{"info_date": "20260702", "direction": "增持"}],
        "repurchase": [{"date": "20260703", "buy_back_value": 500_000_000.0}],
        "restricted_release": [{"date": "20260704", "relieve_date": "20260801", "relieve_shares": 1_000_000}],
        "share_float": [{"date": "20260701", "total": 28_000_000_000}],
        "financial_forecast": [{"info_date": "20260710", "forecast_type": "预增", "forecast_growth_rate_floor": 5.0, "forecast_growth_rate_ceiling": 15.0}],
        "audit_opinion": [{"date": "20260430", "quarter": "2025q4", "opinion": "标准无保留意见"}],
        "litigation": [{"info_date": "20260705", "involved_amount": 10_000_000.0}],
        "material_contract": [{"info_date": "20260706", "max_contract_amount": 2_000_000_000.0}],
        "macro_ir": [{"symbol": "IR0004522", "period_date": "20260720", "data_value": 1.8}],
        "macro_mb": [{"symbol": "MB0000006", "period_date": "20260630", "data_value": 7.2}],
    }
    monkeypatch.setattr(research, "_read_records", lambda bundle, name: rows.get(name, []))

    profiles = research.build_research_profiles(_request(), bundle)

    assert profiles[research.COMPANY_PROFILE_ID].status == "success"
    assert profiles[research.INDUSTRY_PROFILE_ID].metrics["peer_count"] == 3
    assert profiles[research.FLOW_PROFILE_ID].metrics["margin_balance_20d_change_pct"] > 0
    assert profiles[research.OWNERSHIP_PROFILE_ID].metrics["repurchase_record_count"] == 1
    assert profiles[research.EVENT_PROFILE_ID].metrics["forecast_type"] == "预增"
    assert profiles[research.MACRO_PROFILE_ID].metrics["macro_ir0004522"] == 1.8


def test_event_profile_handles_english_audit_and_deduplicates_announcements():
    names = ("audit_opinion", "dividend_amount", "related_party")
    bundle = MarketDataBundle(
        "601628.SH",
        "success",
        "cache",
        {name: _artifact(name) for name in names},
    )
    duplicate_related = {
        "info_date": "20260701",
        "party_name": "同一关联方",
        "trading_method": "共同投资",
        "amount": 100.0,
    }
    records = {
        "audit_opinion": [
            {
                "date": "20260326",
                "quarter": "2025q4",
                "audit_type": "financial_statements",
                "opinion": "unqualified_opinion",
            },
            {
                "date": "20260430",
                "quarter": "2026q1",
                "audit_type": "financial_statements",
                "opinion": "no_audit_performed",
            },
        ],
        "dividend_amount": [
            {
                "announcement_date": "20260326",
                "quarter": "2025q4",
                "event_stage": "预案",
                "total_div_amount": 10_000_000_000.0,
            },
            {
                "announcement_date": "20260620",
                "quarter": "2025q4",
                "event_stage": "决案",
                "total_div_amount": 10_000_000_000.0,
            },
            {
                "announcement_date": "20260701",
                "quarter": "2025q4",
                "event_stage": "方案实施",
                "total_div_amount": 10_000_000_000.0,
            },
        ],
        "related_party": [duplicate_related, dict(duplicate_related)],
    }

    result = research._event_profile(_request(), bundle, records)

    assert result.status == "success"
    assert result.metrics["direction"] == "neutral"
    assert result.metrics["audit_opinion"] == "标准无保留审计意见"
    assert result.metrics["audit_opinion_status"] == "normal"
    assert result.metrics["dividend_plan_count"] == 1
    assert result.metrics["latest_dividend_plan_amount_cny"] == 10_000_000_000.0
    assert result.metrics["related_party_transaction_count"] == 1


def test_ownership_profile_explains_more_holders_as_dispersion():
    bundle = MarketDataBundle(
        "601628.SH",
        "success",
        "cache",
        {"holder_count": _artifact("holder_count")},
    )
    records = {
        "holder_count": [
            {"date": "20260430", "end_date": "20260331", "holders": 100_000},
            {"date": "20260720", "end_date": "20260630", "holders": 120_000},
        ]
    }

    result = research._ownership_profile(_request(), bundle, records)

    assert result.metrics["holder_count_change_pct"] == 20.0
    assert result.metrics["holder_concentration_signal"] == "持股趋于分散"
    assert result.metrics["direction"] == "neutral"
    assert "不能单独解释为利好或利空" in result.assumptions[0]


def test_flow_profile_does_not_call_quarterly_northbound_change_twenty_days():
    bundle = MarketDataBundle(
        "300750.SZ",
        "success",
        "cache",
        {"northbound_holding": _artifact("northbound_holding")},
    )
    records = {
        "northbound_holding": [
            {"date": "20251231", "holding_ratio": 15.71},
            {"date": "20260331", "holding_ratio": 17.27},
            {"date": "20260630", "holding_ratio": 20.28},
        ]
    }

    result = research._flow_profile(bundle, records)

    assert "northbound_holding_ratio_20d_change_pct_point" not in result.metrics
    assert (
        result.metrics["northbound_holding_ratio_latest_report_change_pct_point"]
        == 3.01
    )
    assert result.metrics["northbound_change_interval_days"] == 91
    assert "最近两个披露点" in result.findings[0].claim


def test_missing_financials_do_not_hide_market_behavior(monkeypatch):
    bundle = MarketDataBundle(
        "601628.SH",
        "success",
        "cache",
        {"daily": _artifact("daily")},
    )
    rows = {
        "daily": [
            {"date": f"202501{index + 1:02d}", "close": 10.0 + index * 0.1}
            for index in range(30)
        ]
    }
    monkeypatch.setattr(
        research,
        "_read_records",
        lambda bundle, name: rows.get(name, []),
    )

    profiles = research.build_research_profiles(_request(), bundle)

    assert profiles[research.FUNDAMENTAL_PROFILE_ID].status == "insufficient-evidence"
    assert profiles[research.VALUATION_PROFILE_ID].status == "insufficient-evidence"
    assert profiles[research.MARKET_PROFILE_ID].status == "success"
