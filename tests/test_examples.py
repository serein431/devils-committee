"""Replay the three published A-share examples against the public contract."""

import asyncio
import json
from pathlib import Path

from backend.orchestration import DebateOrchestrator

EX_DIR = Path(__file__).parent / "examples"
EXPECTED_FILES = {
    "600519_moutai_baddata.json",
    "300750_catl_research.json",
    "601318_pingan_research.json",
}


def _load() -> list[Path]:
    return sorted(EX_DIR.glob("*.json"))


def test_exactly_three_a_share_examples_exist():
    assert {path.name for path in _load()} == EXPECTED_FILES


def test_examples_replay_matches_contract():
    for path in _load():
        example = json.loads(path.read_text(encoding="utf-8"))
        assert example["input"]["skill"] == "debate_case", path
        result = asyncio.run(
            DebateOrchestrator().run(example["input"]["topic"])
        ).to_dict()
        expected = example["expected"]

        assert result["meta"]["symbol"] == expected["symbol"], path
        assert result["disclaimer"], path
        assert set(result["meta"]["skills_manifest"]["all_skills"]) == set(
            expected["skill_ids"]
        ), path
        assert result["meta"]["gives_investment_advice"] is False, path

        for item in result["meta"]["skills_manifest"]["results"]:
            assert item["mode"] in {"mock", "live", "cache", "precomputed"}, path
            assert item["status"] in {
                "success",
                "insufficient-evidence",
                "error",
            }, path
