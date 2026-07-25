"""Force the test suite to run fully offline in mock mode, regardless of a
developer's .env (which may point at real panda_data / DeepSeek credentials).

Set BEFORE backend.config is imported so its env-driven CONFIG reads these.
Tests that need a specific mode override CONFIG explicitly via monkeypatch."""
import os
import copy

import pytest

if os.environ.get("RUN_LIVE_INTEGRATION") != "1":
    os.environ["DATA_MODE"] = "mock"
    os.environ["LLM_MODE"] = "mock"
    os.environ["SKILL_MODE"] = "mock"
    os.environ["LLM_MODEL_LABEL"] = "DeepSeek V4 Pro"
    for key in (
        "LLM_API_KEY",
        "LLM_MODEL",
        "DEFAULT_USERNAME",
        "DEFAULT_PASSWORD",
        "PANDA_STATE_DIR",
        "A2A_BEARER_TOKEN",
        "BUILD_COMMIT",
        "PRECOMPUTED_COMMIT",
    ):
        # Empty values prevent backend.config's setdefault-based .env loader
        # from importing live credentials into the ordinary test process.
        os.environ[key] = ""

from backend.research_request import ResearchRequest
from backend.skills.contracts import (
    DatasetArtifact,
    MarketDataBundle,
    SkillFinding,
    SkillResult,
)
from backend.skills.runner import ResearchEvidence


TEST_SKILLS = [
    "skill-corporate-action-adjustment-auditor",
    "skill-survivorship-universe-auditor",
    "skill-portfolio-liquidity-stress-test",
    "skill-index-rebalance-event-study",
    "skill-factor-ranking-sage",
    "skill-model-hpo-evidence-driven",
]


def _research_evidence() -> ResearchEvidence:
    artifact = DatasetArtifact(
        name="daily",
        method="get_stock_daily",
        params={},
        path="/tmp/daily.parquet",
        sha256="daily-hash",
        rows=30,
        mode="mock",
        fetched_at="2026-07-24T00:00:00+00:00",
    )
    bundle = MarketDataBundle(
        "600519.SH",
        "success",
        "mock",
        {"daily": artifact},
    )
    results = {
        skill_id: SkillResult(
            skill_id=skill_id,
            mode="mock",
            status="success",
            duration_ms=1,
            dataset_hashes=["daily-hash"],
            metrics={"sample_size": 30},
            findings=[
                SkillFinding(f"{skill_id} checked", ["daily"], 0.8)
            ],
        )
        for skill_id in TEST_SKILLS
    }
    request = ResearchRequest(
        "600519.SH",
        "cn",
        "分析风险",
        "20240101",
        "20260724",
    )
    return ResearchEvidence(request, bundle, results)


@pytest.fixture
def evidence_fixture():
    return _research_evidence()


@pytest.fixture
def evidence_with_missing_factor():
    evidence = copy.deepcopy(_research_evidence())
    factor = evidence.results["skill-factor-ranking-sage"]
    factor.status = "insufficient-evidence"
    factor.findings = []
    factor.warnings = ["factor report unavailable"]
    return evidence


@pytest.fixture
def evidence_with_missing_survivorship():
    evidence = copy.deepcopy(_research_evidence())
    survivorship = evidence.results["skill-survivorship-universe-auditor"]
    survivorship.status = "insufficient-evidence"
    survivorship.findings = []
    survivorship.warnings = ["delisting_return unavailable"]
    return evidence
