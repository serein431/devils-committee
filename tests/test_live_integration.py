"""Paid and credentialed integration checks for the real PandaAI runtime."""
from __future__ import annotations

import asyncio
import importlib
import os

import pytest


RUN_LIVE = os.environ.get("RUN_LIVE_INTEGRATION") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_LIVE,
    reason="set RUN_LIVE_INTEGRATION=1 to run paid or credentialed checks",
)


if RUN_LIVE:
    # tests/conftest.py deliberately forces the ordinary suite into mock mode.
    # Explicit live opt-in restores the three real adapters for this module.
    os.environ.update(
        LLM_MODE="openai",
        DATA_MODE="panda",
        SKILL_MODE="cli",
    )

    from backend import config as config_module
    from backend import llm as llm_module
    from backend.skills import online as online_module
    from backend.skills import panda as panda_module
    from backend.skills import runner as runner_module

    importlib.reload(config_module)
    importlib.reload(llm_module)
    importlib.reload(panda_module)
    importlib.reload(online_module)
    importlib.reload(runner_module)

    from backend import orchestration as orchestration_module

    importlib.reload(orchestration_module)

    DebateOrchestrator = orchestration_module.DebateOrchestrator
    SkillRunner = runner_module.SkillRunner
    build_market_data_bundle = panda_module.build_market_data_bundle
    get_llm = llm_module.get_llm
else:
    DebateOrchestrator = None
    SkillRunner = None
    build_market_data_bundle = None
    get_llm = None

from backend.research_request import ResearchRequest


SKILL_IDS = {
    "skill-corporate-action-adjustment-auditor",
    "skill-survivorship-universe-auditor",
    "skill-portfolio-liquidity-stress-test",
    "project-index-weight-change-study",
    "skill-factor-ranking-sage",
    "skill-model-hpo-evidence-driven",
}
SYMBOLS = ["600519.SH", "300750.SZ", "601318.SH"]


def test_live_deepseek_v4_pro_minimal_reply():
    model = get_llm()
    assert model.mode == "openai"
    text = model._chat(
        "只回复 OK，不输出任何投资内容。",
        "ping",
    )
    assert text.strip()
    assert "模型说明暂不可用" not in text


def test_live_pandadata_daily_bundle():
    request = ResearchRequest(
        "600519.SH",
        "cn",
        "数据检查",
        "20260716",
        "20260724",
    )
    bundle = build_market_data_bundle(request)
    assert bundle.status == "success"
    assert bundle.datasets["daily"].rows > 0
    assert bundle.datasets["daily"].mode in {"live", "cache"}


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_live_six_skill_results_exist(symbol):
    request = ResearchRequest(
        symbol,
        "cn",
        "完整研究",
        "20240101",
        "20260724",
    )
    evidence = asyncio.run(SkillRunner().prepare(request))
    assert set(evidence.results) == SKILL_IDS
    assert all(
        item.status in {"success", "insufficient-evidence"}
        for item in evidence.results.values()
    )
    assert all(item.mode != "mock" for item in evidence.results.values())


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_live_a2a_research_is_repeatable(symbol):
    request = ResearchRequest(
        symbol,
        "cn",
        f"研究 {symbol} 的多空证据和风险",
        "20240101",
        "20260724",
    )
    result = asyncio.run(DebateOrchestrator().run(request))
    assert result.meta["symbol"] == symbol
    assert result.meta["data_status"] == "success"
    assert result.disclaimer
    assert result.elapsed_sec <= 600
