#!/usr/bin/env python3
"""Build and verify the two offline QuantSkills reports used at request time."""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.config import CONFIG
from backend.research_request import ResearchRequest
from backend.skills.cache import file_sha256
from backend.skills.panda import build_market_data_bundle


FACTOR_SKILL = "skill-factor-ranking-sage"
HPO_SKILL = "skill-model-hpo-evidence-driven"
DEFAULT_UNIVERSE = [
    "600519.SH",
    "300750.SZ",
    "601318.SH",
    "000001.SZ",
    "600036.SH",
    "000858.SZ",
    "002594.SZ",
    "600030.SH",
    "600900.SH",
    "601166.SH",
]

_DATA_UNAVAILABLE = "PandaData evidence unavailable"
_COMMANDS = {
    FACTOR_SKILL: "run_factor_selection.py",
    HPO_SKILL: "run_hpo_search.py",
}


def add_forward_labels(prices: Any) -> Any:
    """Label a signal with next-session entry and a five-session holding period."""
    labelled = prices.sort_values(["symbol", "date"]).copy()
    grouped = labelled.groupby("symbol")
    entry_close = grouped["close"].shift(-1)
    exit_close = grouped["close"].shift(-6)
    labelled["label_start_date"] = grouped["date"].shift(-1)
    labelled["label_end_date"] = grouped["date"].shift(-6)
    labelled["y"] = exit_close / entry_close - 1.0
    return labelled


def _precomputed_root() -> Path:
    root = Path(CONFIG.precomputed_dir).expanduser()
    if not root.is_absolute():
        root = REPO_ROOT / root
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _safe_output_path(path: Path) -> Path:
    root = _precomputed_root()
    requested = path.expanduser()
    if not requested.is_absolute():
        requested = (REPO_ROOT / requested).absolute()
    try:
        requested.parent.resolve().relative_to(root)
        requested.resolve().relative_to(root)
    except (OSError, RuntimeError, ValueError):
        raise ValueError("output path outside PRECOMPUTED_DIR") from None
    if requested.is_symlink():
        raise ValueError("output path outside PRECOMPUTED_DIR")
    return requested


def _safe_output_dir(path: Path) -> Path:
    directory = _safe_output_path(path / ".path-check").parent
    directory.mkdir(parents=True, exist_ok=True)
    try:
        directory.resolve().relative_to(_precomputed_root())
    except (OSError, RuntimeError, ValueError):
        raise ValueError("output path outside PRECOMPUTED_DIR") from None
    if directory.is_symlink():
        raise ValueError("output path outside PRECOMPUTED_DIR")
    return directory


def _safe_source_file(path: str | Path) -> Path:
    root = _precomputed_root()
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = (REPO_ROOT / candidate).absolute()
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        raise RuntimeError(_DATA_UNAVAILABLE) from None
    if candidate.is_symlink() or not candidate.is_file():
        raise RuntimeError(_DATA_UNAVAILABLE)
    return candidate


def build_factor_tables(
    request: ResearchRequest,
    symbols: list[str],
) -> tuple[str, str, str, list[str]]:
    """Build one cross-sectional factor table and its five-day return labels."""
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        raise RuntimeError(_DATA_UNAVAILABLE) from None

    frames: list[Any] = []
    hashes: set[str] = set()
    for symbol in symbols:
        item_request = dataclasses.replace(request, symbol=symbol)
        try:
            bundle = build_market_data_bundle(item_request)
            if (
                bundle.status != "success"
                or not {"factor", "daily_post"} <= set(bundle.datasets)
            ):
                continue
            factor = pd.read_parquet(bundle.datasets["factor"].path)
            prices = pd.read_parquet(bundle.datasets["daily_post"].path)[
                ["date", "symbol", "close"]
            ]
            prices = add_forward_labels(prices)
            merged = factor.merge(
                prices[
                    [
                        "date",
                        "symbol",
                        "y",
                        "label_start_date",
                        "label_end_date",
                    ]
                ],
                on=["date", "symbol"],
                how="inner",
            )
        except Exception:
            continue
        if len(merged) == 0:
            continue
        frames.append(merged)
        hashes.update(bundle.dataset_hashes)

    if not frames:
        raise RuntimeError(_DATA_UNAVAILABLE)
    combined = pd.concat(frames, ignore_index=True).dropna(
        subset=["y", "label_end_date"]
    )
    if len(combined) == 0:
        raise RuntimeError(_DATA_UNAVAILABLE)
    combined["available_date"] = combined["date"]

    output = _safe_output_dir(_precomputed_root() / "inputs")
    metadata_cols = {
        "y",
        "name",
        "available_date",
        "label_start_date",
        "label_end_date",
    }
    feature_cols = [
        column for column in combined.columns if column not in metadata_cols
    ]
    if not {"date", "symbol"} <= set(feature_cols):
        raise RuntimeError(_DATA_UNAVAILABLE)
    factor_cols = [
        column for column in feature_cols if column not in {"date", "symbol"}
    ]
    if not factor_cols:
        raise RuntimeError(_DATA_UNAVAILABLE)

    feature_path = _safe_output_path(output / "features.csv")
    label_path = _safe_output_path(output / "labels.csv")
    universe_path = _safe_output_path(output / "universe.csv")
    combined[["date", "symbol", "available_date", *factor_cols]].to_csv(
        feature_path,
        index=False,
    )
    combined[
        ["date", "symbol", "y", "label_start_date", "label_end_date"]
    ].to_csv(label_path, index=False)
    universe = combined[["date", "symbol"]].drop_duplicates().copy()
    universe["in_universe"] = True
    universe.to_csv(universe_path, index=False)
    return str(feature_path), str(label_path), str(universe_path), sorted(hashes)


def write_json_file(path: Path, payload: dict[str, Any]) -> str:
    """Write an indented UTF-8 JSON file within PRECOMPUTED_DIR."""
    target = _safe_output_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return str(target)


def write_factor_config(feature_path: str, label_path: str) -> str:
    root = _precomputed_root()
    output_root = _safe_output_dir(root / FACTOR_SKILL / "raw")
    return write_json_file(
        root / "factor-config.json",
        {
            "run_name": "devils_committee_factor_selection",
            "output_root": str(output_root),
            "random_seed": 42,
            "mode": "mrmr",
            "selection_count": 6,
            "input": {
                "feature_path": feature_path,
                "label_path": label_path,
            },
            "data": {
                "date_col": "date",
                "ticker_col": "symbol",
                "label_col": "y",
            },
            "validation": {
                "method": "fixed",
                "train_start": 20240101,
                "train_end": 20250131,
                "valid_start": 20250213,
                "valid_end": 20251231,
                "embargo_days": 6,
            },
            "mrmr": {
                "relevance": "f",
                "redundancy": "c",
                "denominator": "mean",
            },
        },
    )


def write_hpo_config(feature_path: str, label_path: str, universe_path: str) -> str:
    root = _precomputed_root()
    output_root = _safe_output_dir(root / HPO_SKILL / "raw")
    return write_json_file(
        root / "hpo-config.json",
        {
            "output_root": str(output_root),
            "config": {
                "task": {
                    "name": "devils_committee_hpo",
                    "seed": 42,
                },
                "input": {
                    "feature_path": feature_path,
                    "label_path": label_path,
                },
                "data": {
                    "start_date": 20240101,
                    "end_date": 20260724,
                    "date_col": "date",
                    "ticker_col": "symbol",
                    "label_col": "y",
                    "universe_path": universe_path,
                    "strict_point_in_time": True,
                    "compute_hash": True,
                },
                "search": {
                    "model_type": "lgbm",
                    "method": "adaptive_tpe",
                    "max_trials": 12,
                    "max_rounds": 3,
                    "trials_per_round": 4,
                    "random_start_trials": 4,
                    "seed": 42,
                    "space": {
                        "num_leaves": {
                            "type": "choice",
                            "values": [15, 31, 63],
                        },
                        "learning_rate": {
                            "type": "loguniform",
                            "low": 0.01,
                            "high": 0.12,
                        },
                        "n_estimators": {
                            "type": "choice",
                            "values": [100, 200, 400],
                        },
                        "subsample": {
                            "type": "uniform",
                            "low": 0.7,
                            "high": 1.0,
                        },
                        "colsample_bytree": {
                            "type": "uniform",
                            "low": 0.7,
                            "high": 1.0,
                        },
                    },
                },
                "model": {"type": "lgbm"},
                "validation": {
                    "method": "fixed_train_valid_test",
                    "train_start": 20240101,
                    "train_end": 20250131,
                    "valid_start": 20250213,
                    "valid_end": 20251231,
                    "test_start": 20260113,
                    "test_end": 20260724,
                    "embargo_days": 6,
                    "min_assets_per_date": 5,
                },
                "training": {"label_window": 5},
                "time": {"trade_lag_days": 1},
                "evaluation": {
                    "inner_loop": "fast_evaluator",
                    "objective": "rankic_ir",
                },
                "llm": {"enabled": False},
                "final_selector": {"enabled": False},
            },
        },
    )


def run_precompute_command(skill_id: str, entry: str, config_path: str) -> None:
    """Run one known QuantSkills entry point without exposing tool output."""
    if _COMMANDS.get(skill_id) != entry:
        raise RuntimeError("QuantSkills precompute unavailable")
    quantskills_root = Path(CONFIG.quantskills_dir).expanduser()
    if not quantskills_root.is_absolute():
        quantskills_root = REPO_ROOT / quantskills_root
    repo = quantskills_root / skill_id
    script = repo / "scripts" / entry
    try:
        resolved_repo = repo.resolve()
        resolved_script = script.resolve()
        resolved_script.relative_to(resolved_repo)
    except (OSError, RuntimeError, ValueError):
        raise RuntimeError("QuantSkills precompute unavailable") from None
    if script.is_symlink() or not script.is_file():
        raise RuntimeError("QuantSkills precompute unavailable")
    try:
        subprocess.run(
            [sys.executable, str(resolved_script), "--input", config_path],
            cwd=str(resolved_repo),
            check=True,
            timeout=900,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("QuantSkills precompute failed") from None


def current_commit() -> str:
    if CONFIG.build_commit:
        return CONFIG.build_commit
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("build commit unavailable") from None


def _newest_file(root: Path, name: str) -> Path:
    try:
        resolved_root = root.resolve()
        candidates = [
            path
            for path in root.rglob(name)
            if (
                path.is_file()
                and not path.is_symlink()
                and path.resolve().is_relative_to(resolved_root)
            )
        ]
        return max(candidates, key=lambda path: path.stat().st_mtime)
    except (OSError, ValueError):
        raise RuntimeError("QuantSkills result unavailable") from None


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        resolved = path.resolve()
        resolved.relative_to(_precomputed_root())
        if path.is_symlink() or not path.is_file():
            raise OSError
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, RuntimeError, UnicodeError, ValueError, json.JSONDecodeError):
        raise RuntimeError("QuantSkills result unavailable") from None
    if not isinstance(payload, dict):
        raise RuntimeError("QuantSkills result unavailable")
    return payload


def collect_result(
    skill_id: str,
    hashes: list[str],
    commit: str,
    universe: list[str],
    feature_path: str,
    label_path: str,
    universe_path: str,
) -> None:
    root = _safe_output_dir(_precomputed_root() / skill_id)
    raw_root = _safe_output_dir(root / "raw")
    if skill_id == FACTOR_SKILL:
        selected_path = _newest_file(raw_root, "selected_factors.json")
        run_dir = selected_path.parent
        selected = _read_json_file(selected_path)
        # The factor skill records the aligned panel size in
        # input_manifest.json under data.num_rows (see reporter.write_artifacts
        # / data_adapter.metadata) — not in selected_factors.json or a
        # run_manifest.json. Read the real observation count from there so the
        # published report does not claim n_obs=0 on a full data run.
        input_manifest = _read_json_file(run_dir / "input_manifest.json")
        manifest_data = input_manifest.get("data")
        n_obs = 0
        if isinstance(manifest_data, dict):
            n_obs = int(manifest_data.get("num_rows", 0) or 0)
        selected_factors = selected.get("selected_factors")
        if not isinstance(selected_factors, list) or not selected_factors:
            raise RuntimeError("QuantSkills result unavailable")
        payload = {
            "selected_factors": selected_factors,
            "metrics": {
                "n_obs": n_obs,
                "train_start": "20240101",
                "train_end": "20250131",
                "valid_start": "20250213",
                "valid_end": "20251231",
            },
            "warnings": [],
        }
    elif skill_id == HPO_SKILL:
        manifest_path = _newest_file(raw_root, "search_manifest.json")
        run_dir = manifest_path.parent
        _read_json_file(manifest_path)
        best_params = _read_json_file(run_dir / "best_params.json")
        trials_path = _safe_source_file(run_dir / "trials.jsonl")
        try:
            trials = [
                json.loads(line)
                for line in trials_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise RuntimeError("QuantSkills result unavailable") from None
        if not all(isinstance(row, dict) for row in trials):
            raise RuntimeError("QuantSkills result unavailable")
        successful = [row for row in trials if row.get("status") == "ok"]
        failed = [row for row in trials if row.get("status") != "ok"]
        if not successful:
            raise RuntimeError("HPO produced no successful trials")
        try:
            validation_score = max(float(row["score"]) for row in successful)
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("QuantSkills result unavailable") from None
        payload = {
            "best_params": best_params,
            "metrics": {
                "successful_trials": len(successful),
                "failed_trials": len(failed),
                "seed": 42,
                "validation_score": validation_score,
            },
            "warnings": [],
        }
    else:
        raise RuntimeError("unsupported precomputed skill")

    feature = _safe_source_file(feature_path)
    label = _safe_source_file(label_path)
    universe_file = _safe_source_file(universe_path)
    precomputed_root = _precomputed_root()
    write_json_file(root / "result.json", payload)
    write_json_file(
        root / "devils-committee-manifest.json",
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "git_commit": commit,
            "dataset_hashes": sorted(set(hashes)),
            "universe": list(universe),
            "source_files": {
                feature.resolve().relative_to(precomputed_root).as_posix(): (
                    file_sha256(feature)
                ),
                label.resolve().relative_to(precomputed_root).as_posix(): (
                    file_sha256(label)
                ),
                universe_file.resolve().relative_to(precomputed_root).as_posix(): (
                    file_sha256(universe_file)
                ),
            },
            "result_file": "result.json",
        },
    )


def main() -> int:
    request = ResearchRequest(
        symbol="600519.SH",
        market="cn",
        question="prepare cross-sectional research",
        start_date=os.environ.get("PRECOMPUTE_START", "20240101"),
        end_date=os.environ.get("PRECOMPUTE_END", "20260724"),
    )
    try:
        feature_path, label_path, universe_path, hashes = build_factor_tables(
            request,
            DEFAULT_UNIVERSE,
        )
    except (OSError, RuntimeError, ValueError):
        print("precompute stopped: PandaData evidence unavailable")
        return 1

    try:
        factor_config = write_factor_config(feature_path, label_path)
        hpo_config = write_hpo_config(feature_path, label_path, universe_path)
        run_precompute_command(
            FACTOR_SKILL,
            "run_factor_selection.py",
            factor_config,
        )
        run_precompute_command(
            HPO_SKILL,
            "run_hpo_search.py",
            hpo_config,
        )
        commit = current_commit()
        collect_result(
            FACTOR_SKILL,
            hashes,
            commit,
            DEFAULT_UNIVERSE,
            feature_path,
            label_path,
            universe_path,
        )
        collect_result(
            HPO_SKILL,
            hashes,
            commit,
            DEFAULT_UNIVERSE,
            feature_path,
            label_path,
            universe_path,
        )
    except (OSError, RuntimeError, ValueError):
        print("precompute stopped: QuantSkills unavailable")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
