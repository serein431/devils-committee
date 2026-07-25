import asyncio

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
        "status_change",
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
