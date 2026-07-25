"""Run one evidence preparation, parallel debate, audit and convergence."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from .agents import (
    AuditAgent,
    BearAgent,
    BullAgent,
    ChairAgent,
    MacroAgent,
    RiskAgent,
)
from .compliance import DISCLAIMER, enforce, enforce_dict, scrub
from .config import CONFIG
from .llm import get_llm
from .models import AuditVerdict, Claim, DebateResult
from .plain import plain_audit, plain_claim
from .research_request import ResearchRequest, symbol_from_text
from .skills.runner import ResearchEvidence, SkillRunner


GLOBAL_BUDGET_SEC = CONFIG.request_budget_sec
PER_AGENT_TIMEOUT_SEC = 120
MAX_AUDIT_ROUNDS = 1

_PUBLIC_TIMEOUT = "研究请求超过内部时间限制。"
_PUBLIC_DATA_ERROR = "研究数据暂不可用，请稍后重试。"
_PUBLIC_INSUFFICIENT = "当前没有足够的授权数据支持研究。"
_PUBLIC_UNSUPPORTED = "当前真实研究只支持 A 股代码。"
_NO_MOCK_SUBSTITUTE = "当前结果没有使用模拟数据代替真实证据。"
_UNAVAILABLE_SKILL_STATUSES = {"error", "insufficient-evidence"}


def _empty_result(
    request: ResearchRequest,
    *,
    data_status: str,
    reason: str,
    elapsed_sec: float,
    skills_manifest: dict | None = None,
) -> DebateResult:
    """Build a compliant public result without exposing private failures."""

    manifest = skills_manifest
    if manifest is None:
        manifest = {
            "data": {
                "symbol": request.symbol,
                "status": data_status,
                "mode": None,
                "dataset_hashes": [],
            },
            "results": [],
            "all_skills": [],
        }
    return enforce(
        DebateResult(
            topic=request.question,
            claims=[],
            verdicts=[],
            consensus=[],
            open_disagreements=[],
            risk_boundaries=[reason, _NO_MOCK_SUBSTITUTE],
            elapsed_sec=elapsed_sec,
            meta={
                "symbol": request.symbol,
                "supported_market": request.supported,
                "data_status": data_status,
                "modes": [],
                "n_claims": 0,
                "n_flags": 0,
                "audit_engine": [],
                "gives_investment_advice": False,
                "recommendation": None,
                "skills_manifest": manifest,
            },
        )
    )


class DebateOrchestrator:
    def __init__(self, emit: Callable[[dict], None] = lambda ev: None) -> None:
        self.runner = SkillRunner()
        self.llm = get_llm()
        self.bull = BullAgent(self.llm)
        self.bear = BearAgent(self.llm)
        self.macro = MacroAgent(self.llm)
        self.risk = RiskAgent(self.llm)
        self.audit = AuditAgent(self.llm)
        self.chair = ChairAgent(self.llm)
        self.emit = emit
        self.result: DebateResult | None = None

    async def run(self, topic: str | ResearchRequest) -> DebateResult:
        """Drain the event stream and return its final compliant result."""

        async for event in self.stream(topic):
            self.emit(event)
        if self.result is None:  # Defensive only; every stream branch sets a result.
            raise RuntimeError("orchestration produced no result")
        return self.result

    async def stream(
        self,
        topic: str | ResearchRequest,
        pace: float = 0.0,
    ):
        """Yield debate events while keeping the whole request in one budget."""

        request = _as_request(topic)
        started = _mono()
        deadline = started + GLOBAL_BUDGET_SEC
        self.result = None

        if not request.supported:
            self.result = _empty_result(
                request,
                data_status="insufficient-evidence",
                reason=_PUBLIC_UNSUPPORTED,
                elapsed_sec=round(_mono() - started, 2),
            )
            yield {"stage": "result", "result": self.result.to_dict()}
            return

        try:
            evidence = await asyncio.wait_for(
                self.runner.prepare(request),
                timeout=GLOBAL_BUDGET_SEC,
            )
        except asyncio.TimeoutError:
            self.result = _empty_result(
                request,
                data_status="error",
                reason=_PUBLIC_TIMEOUT,
                elapsed_sec=round(_mono() - started, 2),
            )
            yield {"stage": "result", "result": self.result.to_dict()}
            return
        except Exception as exc:
            _log_failure("evidence preparation", exc)
            self.result = _empty_result(
                request,
                data_status="error",
                reason=_PUBLIC_DATA_ERROR,
                elapsed_sec=round(_mono() - started, 2),
            )
            yield {"stage": "result", "result": self.result.to_dict()}
            return

        if (
            evidence.bundle.status != "success"
            or not _has_publishable_evidence(evidence)
        ):
            self.result = _empty_result(
                request,
                data_status="insufficient-evidence",
                reason=_PUBLIC_INSUFFICIENT,
                elapsed_sec=round(_mono() - started, 2),
                skills_manifest=self._skills_manifest(evidence, []),
            )
            yield {"stage": "result", "result": self.result.to_dict()}
            return

        try:
            _require_remaining(deadline)
            yield {
                "stage": "argue",
                "symbol": request.symbol,
                "msg": f"四个 Agent 就 {request.symbol} 并行研究…",
            }
            agents = [self.bull, self.bear, self.macro, self.risk]
            claims: list[Claim] = []
            for agent in agents:
                delta_queue: asyncio.Queue[str | object] = asyncio.Queue()
                stream_finished = object()

                async def collect_agent(current=agent):
                    try:
                        return await self._argue(
                            current,
                            evidence,
                            deadline,
                            on_delta=delta_queue.put,
                        )
                    finally:
                        await delta_queue.put(stream_finished)

                task = asyncio.create_task(collect_agent())
                announced = False
                while True:
                    delta = await asyncio.wait_for(
                        delta_queue.get(),
                        timeout=_require_remaining(deadline),
                    )
                    if delta is stream_finished:
                        break
                    if not announced:
                        yield {
                            "stage": "claim_start",
                            "id": f"{agent.side}-1",
                            "agent": agent.__class__.__name__.removesuffix("Agent"),
                            "side": agent.side,
                        }
                        announced = True
                    yield {
                        "stage": "claim_delta",
                        "id": f"{agent.side}-1",
                        "agent": agent.__class__.__name__.removesuffix("Agent"),
                        "side": agent.side,
                        "delta": delta,
                    }

                side_claims = await task
                for claim in side_claims:
                    claim.plain = plain_claim(claim.side)
                    claims.append(claim)
                    if not announced:
                        yield {
                            "stage": "claim_start",
                            "id": claim.id,
                            "agent": claim.agent,
                            "side": claim.side,
                        }
                        yield {
                            "stage": "claim_delta",
                            "id": claim.id,
                            "agent": claim.agent,
                            "side": claim.side,
                            "delta": claim.text,
                        }
                    yield {
                        "stage": "claim",
                        "id": claim.id,
                        "agent": claim.agent,
                        "side": claim.side,
                        "text": claim.text,
                        "plain": claim.plain,
                        "confidence": claim.confidence,
                        "skills_used": claim.skills_used,
                        "evidence": [item.to_dict() for item in claim.evidence],
                    }
                await _pace_within_budget(pace, deadline)

            verdicts: list[AuditVerdict] = []
            for round_index in range(MAX_AUDIT_ROUNDS):
                yield {
                    "stage": "audit",
                    "round": round_index,
                    "msg": "审计 Agent 独立检查每一条论据…",
                }
                await _pace_within_budget(pace, deadline)
                verdicts = await asyncio.wait_for(
                    self.audit.audit(evidence, claims),
                    timeout=_require_remaining(deadline),
                )
                _normalize_missing_evidence_verdicts(claims, verdicts)
                for verdict in verdicts:
                    if verdict.passed:
                        continue
                    yield {
                        "stage": "audit_flag",
                        "claim_id": verdict.claim_id,
                        "status": verdict.status,
                        "reason": verdict.reason,
                        "severity": verdict.severity,
                        "remediation": verdict.remediation,
                        "plain": verdict.plain,
                        "provenance": verdict.provenance,
                        "audit_skill": verdict.audit_skill,
                    }
                    await _pace_within_budget(pace, deadline)

            yield {"stage": "synthesize", "msg": "主持汇总共识与分歧…"}
            synthesis = await asyncio.wait_for(
                self.chair.synthesize(request.symbol, claims, verdicts),
                timeout=_require_remaining(deadline),
            )
        except asyncio.TimeoutError:
            self.result = _empty_result(
                request,
                data_status="error",
                reason=_PUBLIC_TIMEOUT,
                elapsed_sec=round(_mono() - started, 2),
            )
            yield {"stage": "result", "result": self.result.to_dict()}
            return
        except Exception as exc:
            _log_failure("orchestration", exc)
            self.result = _empty_result(
                request,
                data_status="error",
                reason=_PUBLIC_DATA_ERROR,
                elapsed_sec=round(_mono() - started, 2),
            )
            yield {"stage": "result", "result": self.result.to_dict()}
            return

        modes = _evidence_modes(evidence)
        manifest = self._skills_manifest(evidence, claims)
        self.result = enforce(
            DebateResult(
                topic=request.question,
                claims=claims,
                verdicts=verdicts,
                consensus=synthesis["consensus"],
                open_disagreements=synthesis["open_disagreements"],
                risk_boundaries=synthesis["risk_boundaries"],
                elapsed_sec=round(_mono() - started, 2),
                meta={
                    "symbol": request.symbol,
                    "supported_market": request.supported,
                    "data_status": evidence.bundle.status,
                    "modes": modes,
                    "n_claims": len(claims),
                    "n_flags": sum(1 for item in verdicts if not item.passed),
                    "audit_engine": modes,
                    "gives_investment_advice": False,
                    "recommendation": None,
                    "data": manifest["data"],
                    "skills_manifest": manifest,
                },
            )
        )
        yield {
            "stage": "done",
            "elapsed_sec": self.result.elapsed_sec,
            "n_flags": self.result.meta["n_flags"],
        }
        yield {"stage": "result", "result": self.result.to_dict()}

    async def _argue(
        self,
        agent,
        evidence: ResearchEvidence,
        deadline: float,
        on_delta=None,
    ) -> list[Claim]:
        """Return no claims when one agent times out or fails privately."""

        timeout = min(PER_AGENT_TIMEOUT_SEC, max(0.0, deadline - _mono()))
        if timeout <= 0:
            return []
        try:
            if on_delta is None:
                call = agent.argue(evidence)
            else:
                call = agent.argue(evidence, on_delta=on_delta)
            return await asyncio.wait_for(call, timeout=timeout)
        except Exception as exc:
            _log_failure(
                f"agent {getattr(agent, 'side', '?')}",
                exc,
            )
            return []

    def _skills_manifest(
        self,
        evidence: ResearchEvidence,
        claims: list[Claim],
    ) -> dict:
        """Describe the prepared datasets and every returned Skill result."""

        used_by: dict[str, set[str]] = {}
        for claim in claims:
            for skill_id in claim.skills_used:
                used_by.setdefault(skill_id, set()).add(claim.agent)

        results = []
        for skill_id, result in sorted(evidence.results.items()):
            results.append(
                {
                    "skill_id": skill_id,
                    "status": result.status,
                    "mode": result.mode,
                    "duration_ms": result.duration_ms,
                    "dataset_hashes": list(result.dataset_hashes),
                    "used_by": sorted(used_by.get(skill_id, set())),
                    "assumptions": list(result.assumptions),
                    "warnings": list(result.warnings),
                }
            )
        return {
            "data": {
                "symbol": evidence.request.symbol,
                "status": evidence.bundle.status,
                "mode": evidence.bundle.mode,
                "dataset_hashes": evidence.bundle.dataset_hashes,
            },
            "results": results,
            "all_skills": sorted(evidence.results),
        }

    async def audit_claims(self, topic: str | ResearchRequest) -> dict:
        """Prepare once, generate shared-evidence claims and audit them once."""

        request = _as_request(topic)
        started = _mono()
        deadline = started + GLOBAL_BUDGET_SEC

        if not request.supported:
            return _empty_audit_payload(
                request,
                data_status="insufficient-evidence",
                reason=_PUBLIC_UNSUPPORTED,
                elapsed_sec=round(_mono() - started, 2),
            )

        try:
            evidence = await asyncio.wait_for(
                self.runner.prepare(request),
                timeout=GLOBAL_BUDGET_SEC,
            )
        except asyncio.TimeoutError:
            return _empty_audit_payload(
                request,
                data_status="error",
                reason=_PUBLIC_TIMEOUT,
                elapsed_sec=round(_mono() - started, 2),
            )
        except Exception as exc:
            _log_failure("audit evidence preparation", exc)
            return _empty_audit_payload(
                request,
                data_status="error",
                reason=_PUBLIC_DATA_ERROR,
                elapsed_sec=round(_mono() - started, 2),
            )

        if (
            evidence.bundle.status != "success"
            or not _has_publishable_evidence(evidence)
        ):
            return _empty_audit_payload(
                request,
                data_status="insufficient-evidence",
                reason=_PUBLIC_INSUFFICIENT,
                elapsed_sec=round(_mono() - started, 2),
                skills_manifest=self._skills_manifest(evidence, []),
            )

        try:
            _require_remaining(deadline)
            agents = [self.bull, self.bear, self.macro, self.risk]
            gathered = await asyncio.gather(
                *(self._argue(agent, evidence, deadline) for agent in agents)
            )
            claims = [claim for side_claims in gathered for claim in side_claims]
            for claim in claims:
                claim.plain = plain_claim(claim.side)
            verdicts = await asyncio.wait_for(
                self.audit.audit(evidence, claims),
                timeout=_require_remaining(deadline),
            )
            _normalize_missing_evidence_verdicts(claims, verdicts)
        except asyncio.TimeoutError:
            return _empty_audit_payload(
                request,
                data_status="error",
                reason=_PUBLIC_TIMEOUT,
                elapsed_sec=round(_mono() - started, 2),
            )
        except Exception as exc:
            _log_failure("claim audit", exc)
            return _empty_audit_payload(
                request,
                data_status="error",
                reason=_PUBLIC_DATA_ERROR,
                elapsed_sec=round(_mono() - started, 2),
            )

        by_id = {claim.id: claim for claim in claims}
        audits = [
            {
                "claim_id": verdict.claim_id,
                "agent": (
                    by_id[verdict.claim_id].agent
                    if verdict.claim_id in by_id
                    else verdict.claim_id
                ),
                "side": (
                    by_id[verdict.claim_id].side
                    if verdict.claim_id in by_id
                    else ""
                ),
                "claim": (
                    scrub(by_id[verdict.claim_id].text)
                    if verdict.claim_id in by_id
                    else ""
                ),
                "claim_plain": (
                    scrub(by_id[verdict.claim_id].plain)
                    if verdict.claim_id in by_id
                    else ""
                ),
                "status": verdict.status,
                "severity": verdict.severity,
                "reason": scrub(verdict.reason),
                "plain": scrub(verdict.plain),
                "remediation": scrub(verdict.remediation),
                "audit_skill": verdict.audit_skill,
                "provenance": verdict.provenance,
            }
            for verdict in verdicts
        ]
        modes = _evidence_modes(evidence)
        return enforce_dict(
            {
                "symbol": request.symbol,
                "supported_market": request.supported,
                "data_status": evidence.bundle.status,
                "audits": audits,
                "n_claims": len(claims),
                "n_flags": sum(1 for item in verdicts if not item.passed),
                "audit_engine": modes,
                "modes": modes,
                "gives_investment_advice": False,
                "recommendation": None,
                "skills_manifest": self._skills_manifest(evidence, claims),
                "elapsed_sec": round(_mono() - started, 2),
                "disclaimer": DISCLAIMER,
            }
        )


def _empty_audit_payload(
    request: ResearchRequest,
    *,
    data_status: str,
    reason: str,
    elapsed_sec: float,
    skills_manifest: dict | None = None,
) -> dict:
    result = _empty_result(
        request,
        data_status=data_status,
        reason=reason,
        elapsed_sec=elapsed_sec,
        skills_manifest=skills_manifest,
    )
    return enforce_dict(
        {
            "symbol": request.symbol,
            "supported_market": request.supported,
            "data_status": data_status,
            "audits": [],
            "n_claims": 0,
            "n_flags": 0,
            "audit_engine": [],
            "modes": [],
            "gives_investment_advice": False,
            "recommendation": None,
            "skills_manifest": result.meta["skills_manifest"],
            "risk_boundaries": result.risk_boundaries,
            "elapsed_sec": result.elapsed_sec,
            "disclaimer": result.disclaimer,
        }
    )


async def _pace_within_budget(pace: float, deadline: float) -> None:
    if pace > 0:
        await asyncio.wait_for(
            asyncio.sleep(pace),
            timeout=_require_remaining(deadline),
        )


def _require_remaining(deadline: float) -> float:
    remaining = deadline - _mono()
    if remaining <= 0:
        raise asyncio.TimeoutError
    return remaining


def _evidence_modes(evidence: ResearchEvidence) -> list[str]:
    modes = {evidence.bundle.mode}
    modes.update(result.mode for result in evidence.results.values())
    allowed = {"live", "cache", "precomputed", "mock"}
    return sorted(mode for mode in modes if mode in allowed)


def _has_publishable_evidence(evidence: ResearchEvidence) -> bool:
    """Return whether any integrated Skill completed successfully."""

    return any(result.status == "success" for result in evidence.results.values())


def _normalize_missing_evidence_verdicts(
    claims: list[Claim],
    verdicts: list[AuditVerdict],
) -> None:
    """Never publish a pass for a claim that cites unavailable evidence."""

    claims_by_id = {claim.id: claim for claim in claims}
    for verdict in verdicts:
        if verdict.status != "pass":
            continue
        claim = claims_by_id.get(verdict.claim_id)
        if claim is None:
            continue
        unavailable = next(
            (
                item
                for item in claim.evidence
                if item.status in _UNAVAILABLE_SKILL_STATUSES
            ),
            None,
        )
        if unavailable is None:
            continue
        verdict.status = "missing_evidence"
        verdict.reason = (
            f"资料缺失：{unavailable.skill_id} 当前没有可发布证据，"
            "不能完成该论据的审计。"
        )
        verdict.audit_skill = unavailable.skill_id
        verdict.severity = "medium"
        verdict.remediation = "补齐缺失字段并重新运行对应 QuantSkill。"
        verdict.provenance = unavailable.mode
        verdict.plain = plain_audit("missing_evidence")


def _as_request(topic: str | ResearchRequest) -> ResearchRequest:
    if isinstance(topic, ResearchRequest):
        return topic
    return ResearchRequest.from_payload({"topic": topic})


def _log_failure(stage: str, exc: Exception) -> None:
    logging.getLogger("devils-committee").warning(
        "%s failed: %s",
        stage,
        type(exc).__name__,
    )


def _mono() -> float:
    return time.monotonic()


def _extract_symbol(topic: str) -> str:
    return symbol_from_text(topic)[0]


if __name__ == "__main__":
    async def _main():
        orchestrator = DebateOrchestrator(
            emit=lambda event: print(
                "[stream]",
                event.get("stage"),
                event.get("msg", ""),
            )
        )
        result = await orchestrator.run(
            "帮我理解一下 600519 现在多空双方的理由和风险"
        )
        import json

        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2)[:2000])

    asyncio.run(_main())
