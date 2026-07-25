import hashlib
import json
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.skills.precomputed import (
    FACTOR_SKILL,
    HPO_SKILL,
    PrecomputedStore,
    parse_precomputed_findings,
)


def _factor_payload() -> dict:
    return {
        "selected_factors": ["momentum_20d", "turnover"],
        "metrics": {
            "n_obs": 600,
            "train_start": "20240101",
            "train_end": "20250131",
            "valid_start": "20250210",
            "valid_end": "20251231",
        },
        "warnings": ["research only"],
    }


def _hpo_payload() -> dict:
    return {
        "best_params": {"num_leaves": 31, "learning_rate": 0.05},
        "metrics": {
            "successful_trials": 9,
            "failed_trials": 3,
            "seed": 42,
            "validation_score": 0.123,
        },
        "warnings": [],
    }


def _write_run(
    root: Path,
    skill_id: str = FACTOR_SKILL,
    *,
    payload: dict | None = None,
    git_commit: str = "abc123",
    universe: list[str] | None = None,
    source_files: dict[str, str] | None = None,
    result_file: str = "result.json",
    dataset_hashes: list[object] | None = None,
    generated_at: str = "2026-07-24T00:00:00+00:00",
) -> Path:
    inputs = root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    source = inputs / "features.csv"
    source.write_text(
        "date,symbol,x\n20260724,600519.SH,1\n",
        encoding="utf-8",
    )
    if source_files is None:
        source_files = {
            "inputs/features.csv": hashlib.sha256(source.read_bytes()).hexdigest()
        }

    run = root / skill_id
    run.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": generated_at,
        "git_commit": git_commit,
        "dataset_hashes": (
            dataset_hashes
            if dataset_hashes is not None
            else ["b" * 64, "a" * 64, "b" * 64]
        ),
        "universe": universe or ["600519.SH", "300750.SZ", "601318.SH"],
        "source_files": source_files,
        "result_file": result_file,
    }
    (run / "devils-committee-manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    if result_file == "result.json":
        selected_payload = payload or (
            _factor_payload() if skill_id == FACTOR_SKILL else _hpo_payload()
        )
        (run / result_file).write_text(json.dumps(selected_payload), encoding="utf-8")
    return source


def test_matching_factor_report_loads_as_precomputed(tmp_path):
    _write_run(tmp_path)

    result = PrecomputedStore(tmp_path, "abc123").load(
        FACTOR_SKILL,
        "600519.SH",
    )

    assert result.status == "success"
    assert result.mode == "precomputed"
    assert result.dataset_hashes == ["a" * 64, "b" * 64]
    assert result.metrics == _factor_payload()["metrics"]
    assert result.findings[0].claim == "selected factors: momentum_20d, turnover"
    assert result.warnings == ["research only"]


def test_matching_hpo_report_loads_as_precomputed(tmp_path):
    _write_run(tmp_path, HPO_SKILL)

    result = PrecomputedStore(str(tmp_path), "abc123").load(
        HPO_SKILL,
        "600519.SH",
    )

    assert result.status == "success"
    assert result.findings[0].claim == "validated parameter set with score 0.123"
    assert result.findings[0].confidence == 0.8


def test_source_hash_mismatch_is_insufficient(tmp_path):
    source = _write_run(tmp_path)
    source.write_text("changed", encoding="utf-8")

    result = PrecomputedStore(tmp_path, "abc123").load(
        FACTOR_SKILL,
        "600519.SH",
    )

    assert result.status == "insufficient-evidence"
    assert result.dataset_hashes == []
    assert result.warnings == ["precomputed report dataset mismatch"]


def test_commit_mismatch_is_insufficient(tmp_path):
    _write_run(tmp_path, HPO_SKILL, git_commit="old")

    result = PrecomputedStore(tmp_path, "new").load(
        HPO_SKILL,
        "600519.SH",
    )

    assert result.status == "insufficient-evidence"
    assert result.warnings == ["precomputed report commit mismatch"]


@pytest.mark.parametrize("dataset_hashes", [[], ["not-a-sha256"], [None]])
def test_missing_or_invalid_dataset_hashes_are_insufficient(
    tmp_path,
    dataset_hashes,
):
    _write_run(tmp_path, dataset_hashes=dataset_hashes)

    result = PrecomputedStore(tmp_path, "abc123").load(
        FACTOR_SKILL,
        "600519.SH",
    )

    assert result.status == "insufficient-evidence"
    assert result.warnings == ["precomputed report dataset mismatch"]


def test_invalid_generated_at_is_insufficient(tmp_path):
    _write_run(tmp_path, generated_at="not-a-date")

    result = PrecomputedStore(tmp_path, "abc123").load(
        FACTOR_SKILL,
        "600519.SH",
    )

    assert result.status == "insufficient-evidence"
    assert result.warnings == ["precomputed evidence incomplete"]


def test_invalid_factor_date_range_is_insufficient(tmp_path):
    payload = _factor_payload()
    payload["metrics"]["valid_start"] = "20240101"
    _write_run(tmp_path, payload=payload)

    result = PrecomputedStore(tmp_path, "abc123").load(
        FACTOR_SKILL,
        "600519.SH",
    )

    assert result.status == "insufficient-evidence"
    assert result.warnings == ["precomputed evidence incomplete"]


def test_symbol_absent_is_insufficient(tmp_path):
    _write_run(tmp_path, universe=["300750.SZ"])

    result = PrecomputedStore(tmp_path, "abc123").load(
        FACTOR_SKILL,
        "600519.SH",
    )

    assert result.status == "insufficient-evidence"
    assert result.warnings == ["symbol absent from precomputed universe"]


@pytest.mark.parametrize(
    "source_files",
    [
        {"missing.csv": "0" * 64},
        {"../outside.csv": "0" * 64},
        {"/tmp/outside.csv": "0" * 64},
    ],
)
def test_unreadable_or_escaping_source_path_is_insufficient(
    tmp_path,
    source_files,
):
    _write_run(tmp_path, source_files=source_files)

    result = PrecomputedStore(tmp_path, "abc123").load(
        FACTOR_SKILL,
        "600519.SH",
    )

    assert result.status == "insufficient-evidence"
    assert result.warnings == ["precomputed report dataset mismatch"]
    assert all("outside" not in warning for warning in result.warnings)


def test_symlink_source_is_insufficient(tmp_path):
    outside = tmp_path.parent / "outside.csv"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "inputs" / "features.csv"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    _write_run(
        tmp_path,
        source_files={
            "inputs/features.csv": hashlib.sha256(outside.read_bytes()).hexdigest()
        },
    )
    link.unlink()
    link.symlink_to(outside)

    result = PrecomputedStore(tmp_path, "abc123").load(
        FACTOR_SKILL,
        "600519.SH",
    )

    assert result.status == "insufficient-evidence"
    assert result.warnings == ["precomputed report dataset mismatch"]


def test_escaping_result_file_is_reported_as_unreadable(tmp_path):
    outside = tmp_path.parent / "result.json"
    outside.write_text(json.dumps(_factor_payload()), encoding="utf-8")
    _write_run(tmp_path, result_file="../result.json")

    result = PrecomputedStore(tmp_path, "abc123").load(
        FACTOR_SKILL,
        "600519.SH",
    )

    assert result.status == "insufficient-evidence"
    assert result.warnings == ["precomputed report unreadable"]


@pytest.mark.parametrize(
    ("skill_id", "payload"),
    [
        (FACTOR_SKILL, {"selected_factors": [], "metrics": {}}),
        (FACTOR_SKILL, {"selected_factors": ["momentum"], "metrics": {"n_obs": 2}}),
        (HPO_SKILL, {"best_params": {}, "metrics": {}}),
        (
            HPO_SKILL,
            {
                "best_params": {"num_leaves": 31},
                "metrics": {"successful_trials": 1},
            },
        ),
    ],
)
def test_incomplete_factor_or_hpo_evidence_is_insufficient(
    tmp_path,
    skill_id,
    payload,
):
    _write_run(tmp_path, skill_id, payload=payload)

    result = PrecomputedStore(tmp_path, "abc123").load(
        skill_id,
        "600519.SH",
    )

    assert result.status == "insufficient-evidence"
    assert result.warnings == ["precomputed evidence incomplete"]


def test_parser_rejects_unsupported_skill_and_missing_metrics():
    with pytest.raises(ValueError):
        parse_precomputed_findings("skill-unknown", {"metrics": {}})
    with pytest.raises(ValueError):
        parse_precomputed_findings(FACTOR_SKILL, {"selected_factors": ["x"]})


def test_precompute_configs_use_required_research_settings(tmp_path, monkeypatch):
    from scripts import precompute_research

    monkeypatch.setattr(
        precompute_research,
        "CONFIG",
        SimpleNamespace(precomputed_dir=str(tmp_path)),
    )

    factor_path = precompute_research.write_factor_config(
        str(tmp_path / "inputs" / "features.csv"),
        str(tmp_path / "inputs" / "labels.csv"),
    )
    hpo_path = precompute_research.write_hpo_config(
        str(tmp_path / "inputs" / "features.csv"),
        str(tmp_path / "inputs" / "labels.csv"),
        str(tmp_path / "inputs" / "universe.csv"),
    )
    factor = json.loads(Path(factor_path).read_text(encoding="utf-8"))
    hpo = json.loads(Path(hpo_path).read_text(encoding="utf-8"))["config"]

    assert factor["mode"] == "mrmr"
    assert factor["mrmr"] == {
        "relevance": "f",
        "redundancy": "c",
        "denominator": "mean",
    }
    assert factor["validation"] == {
        "method": "fixed",
        "train_start": 20240101,
        "train_end": 20250131,
        "valid_start": 20250213,
        "valid_end": 20251231,
        "embargo_days": 6,
    }
    assert hpo["validation"]["valid_start"] == 20250213
    assert hpo["validation"]["test_start"] == 20260113
    assert hpo["validation"]["embargo_days"] == 6
    assert hpo["time"]["trade_lag_days"] == 1
    assert hpo["data"]["strict_point_in_time"] is True
    assert hpo["data"]["universe_path"] == str(tmp_path / "inputs" / "universe.csv")
    assert hpo["search"]["method"] == "adaptive_tpe"
    assert hpo["evaluation"]["objective"] == "rankic_ir"


def test_forward_labels_start_next_trading_day_and_hold_five_days():
    pd = pytest.importorskip("pandas")
    from scripts import precompute_research

    prices = pd.DataFrame(
        {
            "date": [20240101, 20240102, 20240103, 20240104, 20240105, 20240108, 20240109],
            "symbol": ["600519.SH"] * 7,
            "close": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0],
        }
    )

    labelled = precompute_research.add_forward_labels(prices)

    first = labelled.iloc[0]
    assert first["label_start_date"] == 20240102
    assert first["label_end_date"] == 20240109
    assert first["y"] == pytest.approx(16.0 / 11.0 - 1.0)


def test_collect_result_keeps_symbol_universe_and_hashes_universe_file(tmp_path, monkeypatch):
    from scripts import precompute_research

    monkeypatch.setattr(
        precompute_research,
        "CONFIG",
        SimpleNamespace(precomputed_dir=str(tmp_path)),
    )
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    feature_path = inputs / "features.csv"
    label_path = inputs / "labels.csv"
    universe_path = inputs / "universe.csv"
    feature_path.write_text("date,symbol,x\n20240101,600519.SH,1\n", encoding="utf-8")
    label_path.write_text("date,symbol,y\n20240101,600519.SH,0.1\n", encoding="utf-8")
    universe_path.write_text(
        "date,symbol,in_universe\n20240101,600519.SH,true\n",
        encoding="utf-8",
    )
    raw = tmp_path / FACTOR_SKILL / "raw" / "run-1"
    raw.mkdir(parents=True)
    (raw / "selected_factors.json").write_text(
        json.dumps({"selected_factors": ["x"]}),
        encoding="utf-8",
    )
    # The real factor skill records the aligned panel size in
    # input_manifest.json under data.num_rows (see reporter.write_artifacts),
    # not in selected_factors.json — collect_result reads n_obs from there.
    (raw / "input_manifest.json").write_text(
        json.dumps({"data": {"num_rows": 1}}),
        encoding="utf-8",
    )

    precompute_research.collect_result(
        FACTOR_SKILL,
        ["dataset-hash"],
        "commit-hash",
        ["600519.SH"],
        str(feature_path),
        str(label_path),
        str(universe_path),
    )

    manifest = json.loads(
        (tmp_path / FACTOR_SKILL / "devils-committee-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["universe"] == ["600519.SH"]
    assert "inputs/universe.csv" in manifest["source_files"]


def test_precompute_writer_rejects_path_outside_root(tmp_path, monkeypatch):
    from scripts import precompute_research

    monkeypatch.setattr(
        precompute_research,
        "CONFIG",
        SimpleNamespace(precomputed_dir=str(tmp_path)),
    )

    with pytest.raises(ValueError, match="outside PRECOMPUTED_DIR"):
        precompute_research.write_json_file(
            tmp_path.parent / "outside.json",
            {"secret": "no"},
        )


def test_precompute_writer_rejects_symlinked_parent(tmp_path, monkeypatch):
    from scripts import precompute_research

    outside = tmp_path.parent / "precompute-outside"
    outside.mkdir(exist_ok=True)
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(
        precompute_research,
        "CONFIG",
        SimpleNamespace(precomputed_dir=str(tmp_path)),
    )

    with pytest.raises(ValueError, match="outside PRECOMPUTED_DIR"):
        precompute_research.write_json_file(
            tmp_path / "linked" / "result.json",
            {"secret": "no"},
        )


def test_skill_runner_combines_online_and_precomputed_results(tmp_path, monkeypatch):
    import backend.skills.runner as runner_module
    from backend.research_request import ResearchRequest
    from backend.skills.contracts import MarketDataBundle, SkillResult

    _write_run(tmp_path, FACTOR_SKILL)
    _write_run(tmp_path, HPO_SKILL)
    bundle = MarketDataBundle("600519.SH", "success", "cache")
    online_result = SkillResult(
        skill_id="skill-online",
        mode="cache",
        status="success",
        duration_ms=1,
        dataset_hashes=["daily-hash"],
    )

    class FakeOnlineRunner:
        def __init__(self, timeout_sec):
            assert timeout_sec == 12

        async def run_all(self, request, received_bundle):
            assert received_bundle is bundle
            return [online_result]

    monkeypatch.setattr(
        runner_module,
        "CONFIG",
        SimpleNamespace(
            skill_timeout_sec=12,
            precomputed_dir=str(tmp_path),
            build_commit="abc123",
        ),
    )
    monkeypatch.setattr(
        runner_module,
        "build_market_data_bundle",
        lambda request: bundle,
    )
    monkeypatch.setattr(runner_module, "OnlineSkillRunner", FakeOnlineRunner)

    evidence = asyncio.run(
        runner_module.SkillRunner().prepare(
            ResearchRequest(
                "600519.SH",
                "cn",
                "分析风险",
                "20240101",
                "20260724",
            )
        )
    )

    assert set(evidence.results) == {
        "skill-online",
        FACTOR_SKILL,
        HPO_SKILL,
    }
    assert evidence.results[FACTOR_SKILL].mode == "precomputed"
    assert evidence.results[HPO_SKILL].status == "success"
