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
    monkeypatch.setattr(llm_mod, "CONFIG",
                        dataclasses.replace(CONFIG, llm_mode="openai", llm_api_key="sk-test"))

    calls = {"n": 0}

    def fake_chat(self, system, user, *, want_json=False):
        calls["n"] += 1
        # echo a marker + the role so we can assert routing through the openai path
        role = "audit" if "审计" in system else ("chair" if "主持" in system else "argue")
        return f"[OPENAI:{role}] canned reply {calls['n']}"

    monkeypatch.setattr(llm_mod.OpenAICompatLLM, "_chat", fake_chat, raising=True)
    return calls


def test_full_debate_runs_through_openai_path(monkeypatch):
    calls = _install_fake_openai(monkeypatch)
    # orchestration imports get_llm at call time via llm_mod.get_llm
    from backend import orchestration
    monkeypatch.setattr(orchestration, "get_llm", llm_mod.get_llm)

    r = asyncio.run(orchestration.DebateOrchestrator().run("600519 多空"))

    assert calls["n"] > 0, "openai path was never called"
    # every arguing claim's text came from the openai LLM
    assert all(c.text.startswith("[OPENAI:argue]") for c in r.claims)
    # the pipeline still produced a complete, compliant result
    assert {c.side for c in r.claims} == {"bull", "bear", "macro", "risk"}
    assert r.disclaimer and r.meta["gives_investment_advice"] is False


def test_openai_audit_reasons_route_through_llm(monkeypatch):
    _install_fake_openai(monkeypatch)
    from backend import orchestration
    monkeypatch.setattr(orchestration, "get_llm", llm_mod.get_llm)

    r = asyncio.run(orchestration.DebateOrchestrator().run("NVDA 多空"))
    flagged = r.audit_flags()
    # a mock-provenance flag's reason is phrased by the (fake) openai LLM
    mock_flags = [v for v in flagged if v.provenance != "real-cli"]
    assert mock_flags, "expected at least one non-cli flag on NVDA"
    assert any(v.reason.startswith("[OPENAI:audit]") for v in mock_flags)
