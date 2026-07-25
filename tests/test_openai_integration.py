"""Integration: a FULL debate through the openai (real-LLM) path, no network.

The unit tests (test_llm.py) prove request assembly; this proves the whole
DebateOrchestrator pipeline runs when get_llm() returns the real OpenAICompatLLM —
argue / audit_reason / chair all route through it, and compliance still applies.
De-risks the #1 real-mode integration before the DeepSeek key arrives."""
import asyncio
import dataclasses

from backend import llm as llm_mod
from backend.config import CONFIG


def _install_fake_openai(monkeypatch):
    """Force get_llm() -> OpenAICompatLLM, but bypass httpx with canned replies."""
    monkeypatch.setattr(
        llm_mod,
        "CONFIG",
        dataclasses.replace(
            CONFIG,
            llm_mode="openai",
            llm_api_key="sk-test",
            llm_model="ep-test",
        ),
    )

    calls = {"n": 0}

    def fake_chat(self, system, user, *, want_json=False):
        calls["n"] += 1
        # echo a marker + the role so we can assert routing through the openai path
        role = "audit" if "审计" in system else ("chair" if "主持" in system else "argue")
        return f"[OPENAI:{role}] canned reply {calls['n']}"

    def fake_chat_stream(self, system, user):
        calls["n"] += 1
        yield "[OPENAI:argue] "
        yield f"canned reply {calls['n']}"

    monkeypatch.setattr(llm_mod.OpenAICompatLLM, "_chat", fake_chat, raising=True)
    monkeypatch.setattr(
        llm_mod.OpenAICompatLLM,
        "_chat_stream",
        fake_chat_stream,
        raising=True,
    )
    return calls


def test_full_debate_runs_through_openai_path(monkeypatch, evidence_fixture):
    calls = _install_fake_openai(monkeypatch)
    from backend import orchestration
    monkeypatch.setattr(orchestration, "get_llm", llm_mod.get_llm)

    async def prepare(self, request):
        return evidence_fixture

    monkeypatch.setattr(orchestration.SkillRunner, "prepare", prepare)

    r = asyncio.run(orchestration.DebateOrchestrator().run("600519 多空"))

    assert calls["n"] > 0, "openai path was never called"
    # every arguing claim's text came from the openai LLM
    assert all(c.text.startswith("[OPENAI:argue]") for c in r.claims)
    # the pipeline still produced a complete, compliant result
    assert {c.side for c in r.claims} == {"bull", "bear", "macro", "risk"}
    assert r.disclaimer and r.meta["gives_investment_advice"] is False


def test_openai_audit_reasons_route_through_llm(monkeypatch, evidence_fixture):
    _install_fake_openai(monkeypatch)
    evidence_fixture.results[
        "skill-corporate-action-adjustment-auditor"
    ].outcome = "fail"
    from backend import orchestration
    monkeypatch.setattr(orchestration, "get_llm", llm_mod.get_llm)

    async def prepare(self, request):
        return evidence_fixture

    monkeypatch.setattr(orchestration.SkillRunner, "prepare", prepare)

    r = asyncio.run(orchestration.DebateOrchestrator().run("600519 多空"))
    flagged = r.audit_flags()
    assert flagged
    assert any(v.reason.startswith("[OPENAI:audit]") for v in flagged)
