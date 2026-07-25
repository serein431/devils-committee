import asyncio

from backend.skills import online as online_module
from backend.research_request import ResearchRequest
from backend.skills.contracts import (
    DatasetArtifact,
    MarketDataBundle,
    SkillFinding,
    SkillResult,
)
from backend.skills.online import (
    OnlineSkillRunner,
    liquidity_parameters,
    report_to_result,
)


def _artifact(name: str) -> DatasetArtifact:
    return DatasetArtifact(
        name=name,
        method=name,
        params={},
        path=f"/tmp/{name}.parquet",
        sha256=f"hash-{name}",
        rows=10,
        mode="cache",
        fetched_at="2026-07-24T00:00:00+00:00",
    )


def _request() -> ResearchRequest:
    return ResearchRequest("600519.SH", "cn", "分析风险", "20240101", "20260724")


def _bundle() -> MarketDataBundle:
    names = (
        "daily",
        "daily_post",
        "adj_factor",
        "dividend",
        "cash_dividend",
        "split",
        "status_change",
        "stock_detail",
        "trade_list_start",
        "trade_list_end",
        "index_weights",
        "index_daily",
    )
    return MarketDataBundle(
        "600519.SH",
        "success",
        "cache",
        {name: _artifact(name) for name in names},
    )


def _success(skill_id: str, bundle: MarketDataBundle) -> SkillResult:
    return SkillResult(
        skill_id=skill_id,
        mode="cache",
        status="success",
        duration_ms=1,
        dataset_hashes=bundle.dataset_hashes,
        findings=[SkillFinding("checked", ["daily"], 0.8)],
    )


def test_all_four_online_skills_return_one_result(monkeypatch):
    bundle = _bundle()
    runner = OnlineSkillRunner()
    monkeypatch.setattr(
        runner,
        "run_adjustments",
        lambda request, bundle: _success(
            "skill-corporate-action-adjustment-auditor", bundle
        ),
    )
    monkeypatch.setattr(
        runner,
        "run_survivorship",
        lambda request, bundle: _success(
            "skill-survivorship-universe-auditor", bundle
        ),
    )
    monkeypatch.setattr(
        runner,
        "run_liquidity",
        lambda request, bundle: _success(
            "skill-portfolio-liquidity-stress-test", bundle
        ),
    )
    monkeypatch.setattr(
        runner,
        "run_index_event",
        lambda request, bundle: _success(
            "skill-index-rebalance-event-study", bundle
        ),
    )

    results = asyncio.run(runner.run_all(_request(), bundle))

    assert {item.skill_id for item in results} == {
        "skill-corporate-action-adjustment-auditor",
        "skill-survivorship-universe-auditor",
        "skill-portfolio-liquidity-stress-test",
        "skill-index-rebalance-event-study",
    }
    assert all(item.dataset_hashes for item in results)


def test_timeout_only_marks_the_slow_skill(monkeypatch):
    import time

    runner = OnlineSkillRunner(timeout_sec=0.01)

    def slow(request, bundle):
        time.sleep(0.05)
        return _success("skill-corporate-action-adjustment-auditor", bundle)

    monkeypatch.setattr(runner, "run_adjustments", slow)
    monkeypatch.setattr(
        runner,
        "run_survivorship",
        lambda request, bundle: _success(
            "skill-survivorship-universe-auditor", bundle
        ),
    )
    monkeypatch.setattr(
        runner,
        "run_liquidity",
        lambda request, bundle: _success(
            "skill-portfolio-liquidity-stress-test", bundle
        ),
    )
    monkeypatch.setattr(
        runner,
        "run_index_event",
        lambda request, bundle: _success(
            "skill-index-rebalance-event-study", bundle
        ),
    )

    results = asyncio.run(runner.run_all(_request(), _bundle()))

    assert sum(item.status == "error" for item in results) == 1
    assert sum(item.status == "success" for item in results) == 3


def test_missing_delisting_return_never_becomes_success():
    result = report_to_result(
        "skill-survivorship-universe-auditor",
        {"status": "pass", "findings": []},
        "cache",
        1,
        ["hash-trade-list"],
        forced_warning="delisting_return unavailable",
    )

    assert result.status == "insufficient-evidence"
    assert "delisting_return" in " ".join(result.warnings)


def test_missing_adjustment_dataset_is_insufficient_not_error():
    bundle = _bundle()
    bundle.datasets.pop("adj_factor")

    result = OnlineSkillRunner().run_adjustments(_request(), bundle)

    assert result.status == "insufficient-evidence"
    assert result.warnings == ["adj_factor dataset unavailable"]


def test_adjustment_rows_use_iso_dates_and_explicit_cash_split_sources(monkeypatch):
    records = {
        "daily": [
            {"date": "20240101", "close": 100.0},
            {"date": "20240102", "close": 99.0},
        ],
        "daily_post": [
            {"date": "20240101", "close": 100.0},
            {"date": "20240102", "close": 100.0},
        ],
        # ex_factor includes cash/share effects and must not be treated as a split.
        "adj_factor": [{"ex_date": "20240102", "ex_factor": 9.0}],
        "dividend": [],
        "cash_dividend": [
            {"ex_date": "20240102", "div_cash_gross": 12.3, "round_lot": 10.0}
        ],
        "split": [],
    }
    monkeypatch.setattr(
        online_module,
        "_read_records",
        lambda bundle, name: records[name],
    )

    rows, warning = online_module._adjustment_rows(_request(), _bundle())

    assert warning == ""
    assert [row["date"] for row in rows] == ["2024-01-01", "2024-01-02"]
    assert rows[1]["cash_dividend"] == 1.23
    assert rows[1]["split_factor"] == 1.0


def test_universe_rows_use_stock_detail_lifecycle_dates(monkeypatch):
    records = {
        "trade_list_start": [{"date": "20240101", "symbol": "600519.SH"}],
        "trade_list_end": [{"date": "20240131", "symbol": "600519.SH"}],
        "status_change": [],
        "stock_detail": [
            {
                "symbol": "600519.SH",
                "listed_date": "1991-08-27",
                "de_listed_date": "0000-00-00",
            }
        ],
    }
    monkeypatch.setattr(
        online_module,
        "_read_records",
        lambda bundle, name: records[name],
    )

    rows, warning = online_module._universe_rows(_request(), _bundle())

    assert warning == ""
    assert [row["date"] for row in rows] == ["2024-01-01", "2026-07-24"]
    assert all(row["listed_at"] == "1991-08-27" for row in rows)
    assert all(row["delisted_at"] == "" for row in rows)


def test_missing_survivorship_datasets_are_insufficient_not_error():
    bundle = _bundle()
    bundle.datasets.pop("trade_list_start")
    bundle.datasets.pop("status_change")

    result = OnlineSkillRunner().run_survivorship(_request(), bundle)

    assert result.status == "insufficient-evidence"
    assert result.warnings == [
        "status_change and trade_list_start datasets unavailable"
    ]


def test_liquidity_defaults_are_labeled_as_assumptions():
    params, assumptions = liquidity_parameters(_request(), avg_amount=20_000_000.0)

    assert params["position_value"] == 100000.0
    assert params["spread_bps"] == 10.0
    assert any("position_value" in item for item in assumptions)
    assert any("spread_bps" in item for item in assumptions)


def test_report_to_result_uses_findings_limitations_and_deduped_hashes():
    result = report_to_result(
        "skill-corporate-action-adjustment-auditor",
        {
            "status": "fail",
            "findings": [
                {
                    "impact": "adjustment mismatch",
                    "evidence": {
                        "symbol": "600519.SH",
                        "date": "20240102",
                        "reasons": ["jump", "factor mismatch"],
                        "numeric": 1.5,
                    },
                }
            ],
            "limitations": ["dividend field incomplete"],
            "input_summary": {"rows": 2},
        },
        "cache",
        4,
        ["daily-hash", "daily-hash", "factor-hash"],
    )

    assert result.status == "success"
    assert result.dataset_hashes == ["daily-hash", "factor-hash"]
    assert result.findings[0].claim == "adjustment mismatch"
    assert result.findings[0].evidence_refs == ["600519.SH", "20240102"]
    assert result.metrics == {"rows": 2}
    assert result.warnings == ["dividend field incomplete"]


def test_index_rows_do_not_invent_a_missing_announcement_date(monkeypatch):
    records = {
        "index_weights": [{"date": "20240102", "weight": 0.1}],
        "daily": [
            {"trade_date": "20240101", "close": 100.0, "volume": 1000.0},
            {"trade_date": "20240102", "close": 101.0, "volume": 1100.0},
            {"trade_date": "20240103", "close": 102.0, "volume": 1200.0},
        ],
        "index_daily": [
            {"trade_date": "20240101", "close": 200.0},
            {"trade_date": "20240102", "close": 201.0},
            {"trade_date": "20240103", "close": 202.0},
        ],
    }
    monkeypatch.setattr(
        online_module,
        "_read_records",
        lambda bundle, name: records[name],
    )

    rows, warning = online_module._event_rows(_request(), _bundle())

    assert rows
    assert all(row["announcement_date"] == "" for row in rows)
    assert all(row["effective_date"] == "2024-01-02" for row in rows)
    assert "announcement_date unavailable" in warning


def test_index_event_missing_announcement_cannot_be_published_as_success(monkeypatch):
    runner = OnlineSkillRunner()
    monkeypatch.setattr(
        online_module,
        "_event_rows",
        lambda request, bundle: ([{"event_id": "event-1"}], "announcement_date unavailable"),
    )
    monkeypatch.setattr(
        runner,
        "_invoke",
        lambda *args: ({"status": "pass", "findings": []}, 1),
    )

    result = runner.run_index_event(_request(), _bundle())

    assert result.status == "insufficient-evidence"
    assert "announcement_date unavailable" in result.warnings
