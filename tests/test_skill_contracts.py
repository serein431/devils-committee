from backend.skills.contracts import (
    MarketDataBundle,
    SkillFinding,
    SkillResult,
)


def test_skill_result_serializes_traceable_evidence():
    result = SkillResult(
        skill_id="skill-corporate-action-adjustment-auditor",
        mode="live",
        status="success",
        duration_ms=42,
        dataset_hashes=["abc"],
        findings=[
            SkillFinding(
                "复权记录可核对",
                ["daily", "adj_factor"],
                0.9,
            )
        ],
    )

    payload = result.to_dict()

    assert payload["status"] == "success"
    assert payload["dataset_hashes"] == ["abc"]
    assert payload["findings"][0]["evidence_refs"] == ["daily", "adj_factor"]


def test_market_data_bundle_marks_missing_daily_evidence():
    bundle = MarketDataBundle.insufficient(
        symbol="600519.SH",
        reason="daily dataset unavailable",
    )

    assert bundle.status == "insufficient-evidence"
    assert bundle.mode == "live"
    assert bundle.datasets == {}
    assert bundle.warnings == ["daily dataset unavailable"]
    assert bundle.dataset_hashes == []
