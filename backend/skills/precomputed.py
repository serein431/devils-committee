"""Read build-bound QuantSkills reports without trusting local paths blindly."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .cache import file_sha256
from .contracts import SkillFinding, SkillResult


FACTOR_SKILL = "skill-factor-ranking-sage"
HPO_SKILL = "skill-model-hpo-evidence-driven"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_DATE_RE = re.compile(r"^\d{8}$")


def _valid_date(value: object) -> str | None:
    rendered = str(value)
    if not _DATE_RE.fullmatch(rendered):
        return None
    try:
        datetime.strptime(rendered, "%Y%m%d")
    except ValueError:
        return None
    return rendered


def _valid_generated_at(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def insufficient_result(skill_id: str, warning: str) -> SkillResult:
    """Return a public, detail-free result when saved evidence cannot be used."""
    return SkillResult(
        skill_id=skill_id,
        mode="precomputed",
        status="insufficient-evidence",
        duration_ms=0,
        dataset_hashes=[],
        warnings=[warning],
    )


def parse_precomputed_findings(
    skill_id: str,
    payload: dict[str, Any],
) -> list[SkillFinding]:
    """Convert the two supported report shapes into the shared result contract."""
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("metrics missing")

    if skill_id == FACTOR_SKILL:
        selected = payload.get("selected_factors")
        required = {
            "n_obs",
            "train_start",
            "train_end",
            "valid_start",
            "valid_end",
        }
        if (
            not isinstance(selected, list)
            or not selected
            or not required <= set(metrics)
        ):
            raise ValueError("factor evidence incomplete")
        dates = [
            _valid_date(metrics[key])
            for key in ("train_start", "train_end", "valid_start", "valid_end")
        ]
        if any(value is None for value in dates):
            raise ValueError("factor evidence incomplete")
        train_start, train_end, valid_start, valid_end = dates
        if not train_start <= train_end < valid_start <= valid_end:
            raise ValueError("factor evidence incomplete")
        return [
            SkillFinding(
                claim=f"selected factors: {', '.join(map(str, selected))}",
                evidence_refs=[
                    "selected_factors.json",
                    "run_manifest.json",
                    "input_manifest.json",
                ],
                confidence=0.85,
            )
        ]

    if skill_id == HPO_SKILL:
        best_params = payload.get("best_params")
        required = {
            "successful_trials",
            "failed_trials",
            "seed",
            "validation_score",
        }
        if (
            not isinstance(best_params, dict)
            or not best_params
            or not required <= set(metrics)
        ):
            raise ValueError("HPO evidence incomplete")
        return [
            SkillFinding(
                claim=(
                    "parameter search selected a set with validation score "
                    f"{metrics['validation_score']}"
                ),
                evidence_refs=[
                    "best_params.json",
                    "search_manifest.json",
                    "trials.jsonl",
                ],
                confidence=0.8,
            )
        ]

    raise ValueError("unsupported precomputed skill")


class PrecomputedStore:
    """Load precomputed reports only when their commit and sources still match."""

    def __init__(self, root: str | Path, build_commit: str) -> None:
        self.root = Path(root)
        self.build_commit = build_commit

    @staticmethod
    def _safe_file(base: Path, relative_path: object) -> Path | None:
        if not isinstance(relative_path, str) or not relative_path:
            return None
        requested = Path(relative_path)
        if requested.is_absolute():
            return None
        try:
            resolved_base = base.resolve()
            candidate = base / requested
            resolved = candidate.resolve()
            resolved.relative_to(resolved_base)
        except (OSError, RuntimeError, ValueError):
            return None
        if candidate.is_symlink() or not candidate.is_file():
            return None
        return candidate

    def _run_dir(self, skill_id: str) -> Path | None:
        if skill_id not in {FACTOR_SKILL, HPO_SKILL}:
            return None
        try:
            root = self.root.resolve()
            run_dir = self.root / skill_id
            run_dir.resolve().relative_to(root)
        except (OSError, RuntimeError, ValueError):
            return None
        if run_dir.is_symlink() or not run_dir.is_dir():
            return None
        return run_dir

    def load(self, skill_id: str, symbol: str) -> SkillResult:
        run_dir = self._run_dir(skill_id)
        if run_dir is None:
            return insufficient_result(
                skill_id,
                "precomputed manifest unavailable",
            )

        manifest_path = self._safe_file(
            run_dir,
            "devils-committee-manifest.json",
        )
        if manifest_path is None:
            return insufficient_result(
                skill_id,
                "precomputed manifest unavailable",
            )

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError
            result_path = self._safe_file(run_dir, manifest.get("result_file"))
            if result_path is None:
                raise ValueError
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return insufficient_result(
                skill_id,
                "precomputed report unreadable",
            )

        if self.build_commit and manifest.get("git_commit") != self.build_commit:
            return insufficient_result(
                skill_id,
                "precomputed report commit mismatch",
            )

        if not _valid_generated_at(manifest.get("generated_at")):
            return insufficient_result(
                skill_id,
                "precomputed evidence incomplete",
            )

        universe = manifest.get("universe")
        if not isinstance(universe, list) or symbol not in universe:
            return insufficient_result(
                skill_id,
                "symbol absent from precomputed universe",
            )

        source_files = manifest.get("source_files")
        if not isinstance(source_files, dict):
            return insufficient_result(
                skill_id,
                "precomputed report dataset mismatch",
            )
        for relative_path, expected_hash in source_files.items():
            source_path = self._safe_file(self.root, relative_path)
            if source_path is None or not isinstance(expected_hash, str):
                return insufficient_result(
                    skill_id,
                    "precomputed report dataset mismatch",
                )
            try:
                actual_hash = file_sha256(source_path)
            except OSError:
                return insufficient_result(
                    skill_id,
                    "precomputed report dataset mismatch",
                )
            if actual_hash != expected_hash:
                return insufficient_result(
                    skill_id,
                    "precomputed report dataset mismatch",
                )

        try:
            findings = parse_precomputed_findings(skill_id, payload)
        except ValueError:
            return insufficient_result(
                skill_id,
                "precomputed evidence incomplete",
            )

        raw_hashes = manifest.get("dataset_hashes")
        dataset_hashes = (
            sorted(
                {
                    item.lower()
                    for item in raw_hashes
                    if isinstance(item, str) and _SHA256_RE.fullmatch(item)
                }
            )
            if isinstance(raw_hashes, list)
            else []
        )
        if not dataset_hashes:
            return insufficient_result(
                skill_id,
                "precomputed report dataset mismatch",
            )
        raw_warnings = payload.get("warnings")
        warnings = (
            [item for item in raw_warnings if isinstance(item, str)]
            if isinstance(raw_warnings, list)
            else []
        )
        return SkillResult(
            skill_id=skill_id,
            mode="precomputed",
            status="success",
            duration_ms=0,
            dataset_hashes=dataset_hashes,
            metrics=dict(payload["metrics"]),
            findings=findings,
            warnings=warnings,
        )
