"""Prepare one shared data bundle and its six integrated QuantSkill results."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..config import CONFIG
from ..research_request import ResearchRequest
from .contracts import MarketDataBundle, SkillFinding, SkillResult
from .data import DailyBars, get_stock_daily
from .online import OnlineSkillRunner
from .panda import build_market_data_bundle
from .precomputed import FACTOR_SKILL, HPO_SKILL, PrecomputedStore


MOCK_SKILL_IDS = [
    "skill-corporate-action-adjustment-auditor",
    "skill-survivorship-universe-auditor",
    "skill-portfolio-liquidity-stress-test",
    "skill-index-rebalance-event-study",
    "skill-factor-ranking-sage",
    "skill-model-hpo-evidence-driven",
]


@dataclass
class ResearchEvidence:
    request: ResearchRequest
    bundle: MarketDataBundle
    results: dict[str, SkillResult]


def build_mock_results(bundle: MarketDataBundle) -> dict[str, SkillResult]:
    findings = {
        "skill-portfolio-liquidity-stress-test": [
            SkillFinding("mock liquidity estimate", ["daily"], 0.5)
        ],
        "skill-index-rebalance-event-study": [
            SkillFinding("mock index event estimate", ["daily"], 0.5)
        ],
        "skill-factor-ranking-sage": [
            SkillFinding("mock factor ranking", ["daily"], 0.5)
        ],
    }
    return {
        skill_id: SkillResult(
            skill_id=skill_id,
            mode="mock",
            status="success",
            duration_ms=0,
            dataset_hashes=bundle.dataset_hashes,
            findings=findings.get(skill_id, []),
            warnings=[
                "offline deterministic mock; not valid for public evidence"
            ],
        )
        for skill_id in MOCK_SKILL_IDS
    }


class SkillRunner:
    def __init__(self) -> None:
        self._bars_cache: dict[str, DailyBars] = {}

    async def prepare(self, request: ResearchRequest) -> ResearchEvidence:
        bundle = await asyncio.to_thread(build_market_data_bundle, request)
        if bundle.status != "success":
            return ResearchEvidence(request, bundle, {})
        if bundle.mode == "mock":
            return ResearchEvidence(
                request,
                bundle,
                build_mock_results(bundle),
            )

        online = await OnlineSkillRunner(CONFIG.skill_timeout_sec).run_all(
            request,
            bundle,
        )
        store = PrecomputedStore(
            CONFIG.precomputed_dir,
            CONFIG.precomputed_commit or CONFIG.build_commit,
        )
        all_results = {item.skill_id: item for item in online}
        online_factor = all_results.get(FACTOR_SKILL)
        if online_factor is None or online_factor.status != "success":
            saved_factor = store.load(FACTOR_SKILL, request.symbol)
            if saved_factor.status == "success" or online_factor is None:
                all_results[FACTOR_SKILL] = saved_factor
        all_results[HPO_SKILL] = store.load(HPO_SKILL, request.symbol)
        return ResearchEvidence(
            request,
            bundle,
            all_results,
        )

    def bars(self, symbol: str) -> DailyBars:
        """Temporary read-only compatibility for the current orchestrator."""

        if symbol not in self._bars_cache:
            self._bars_cache[symbol] = get_stock_daily(symbol)
        return self._bars_cache[symbol]

    def data_ref(self, symbol: str) -> str:
        """Temporary compatibility; agents no longer call this method."""

        bars = self.bars(symbol)
        date_range = (
            f"{bars.dates[0]}..{bars.dates[-1]}"
            if bars.dates
            else "n/a"
        )
        return f"{symbol} {date_range} ({bars.source})"
