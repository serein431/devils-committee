"""De-risk the real DeepSeek/OpenAI path BEFORE the key arrives (LLM_MODE=openai).

No network: we inject a fake httpx client and assert the request body — model,
temperature, persona system prompt, and the evidence JSON — is assembled right,
and that get_llm() switches modes correctly. When the Feishu key lands, these
lock down that only the transport changes, not the contract."""
import dataclasses
import pytest
from backend import llm


class _FakeResp:
    def __init__(self, content):
        self._c = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._c}}]}


class _FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, url, json):          # noqa: A002 (mirror httpx signature)
        self.calls.append((url, json))
        return _FakeResp("MOCKED_REPLY")


class _FakeStreamResp:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"真实"}}]}'
        yield 'data: {"choices":[{"delta":{"content":"增量"}}]}'
        yield "data: [DONE]"


class _FakeStreamingClient(_FakeClient):
    def stream(self, method, url, json):  # noqa: A002 (mirror httpx signature)
        self.calls.append((method, url, json))
        return _FakeStreamResp()


def _openai_without_network():
    """Build OpenAICompatLLM without running __init__ (no httpx/network)."""
    obj = llm.OpenAICompatLLM.__new__(llm.OpenAICompatLLM)
    obj._client = _FakeClient()
    obj._httpx = None
    return obj


def test_argue_builds_persona_system_and_evidence_user(monkeypatch):
    monkeypatch.setattr(
        llm,
        "CONFIG",
        dataclasses.replace(llm.CONFIG, llm_model="test-model"),
    )
    o = _openai_without_network()
    evidence = [{"skill": "skill-factor-ranking-sage", "summary": "正向排序",
                 "metrics": {"ic": 0.04}}]
    out = o.argue(side="bull", symbol="600519.SH", evidence=evidence)
    assert out == "MOCKED_REPLY"
    url, body = o._client.calls[0]
    assert url == "/chat/completions"
    assert body["model"] == "test-model"
    assert body["temperature"] == llm.CONFIG.llm_temperature
    system, user = body["messages"][0]["content"], body["messages"][1]["content"]
    assert llm.PERSONAS["bull"]["name"] in system
    assert "买入" in system or "荐股" in system    # persona forbids buy/sell advice
    assert "outcome=null 是正常值" in system
    assert "不得扩展为方向信号" in system
    assert "findings 本身不等于异常" in system
    assert "600519.SH" in user
    assert "skill-factor-ranking-sage" in user     # evidence JSON is passed through


def test_argue_stream_forwards_real_sse_deltas(monkeypatch):
    monkeypatch.setattr(
        llm,
        "CONFIG",
        dataclasses.replace(llm.CONFIG, llm_model="test-model"),
    )
    o = llm.OpenAICompatLLM.__new__(llm.OpenAICompatLLM)
    o._client = _FakeStreamingClient()
    o._httpx = None

    deltas = list(
        o.argue_stream(
            side="bull",
            symbol="600519.SH",
            evidence=[{"skill": "skill-factor-ranking-sage"}],
        )
    )

    assert deltas == ["真实", "增量"]
    method, url, body = o._client.calls[0]
    assert method == "POST"
    assert url == "/chat/completions"
    assert body["stream"] is True
    assert "600519.SH" in body["messages"][1]["content"]


def test_audit_reason_uses_audit_persona_and_status():
    o = _openai_without_network()
    o.audit_reason(status="selection_bias", symbol="600519.SH",
                   detail={"proven_issues": ["cherry-picked universe"]})
    _, body = o._client.calls[0]
    system, user = body["messages"][0]["content"], body["messages"][1]["content"]
    assert llm.PERSONAS["audit"]["name"] in system
    assert "selection_bias" in user
    assert "cherry-picked universe" in user


def test_chair_line_uses_chair_persona():
    o = _openai_without_network()
    o.chair_line(symbol="300750.SZ", kind="consensus", payload=["a", "b"])
    _, body = o._client.calls[0]
    assert llm.PERSONAS["chair"]["name"] in body["messages"][0]["content"]


def test_get_llm_switches_on_mode_and_key(monkeypatch):
    base = llm.CONFIG
    # mock mode -> MockLLM regardless of key
    monkeypatch.setattr(llm, "CONFIG", dataclasses.replace(base, llm_mode="mock"))
    assert isinstance(llm.get_llm(), llm.MockLLM)
    # Live mode must never silently publish mock wording.
    monkeypatch.setattr(llm, "CONFIG",
                        dataclasses.replace(base, llm_mode="openai", llm_api_key=""))
    with pytest.raises(RuntimeError, match="configuration unavailable"):
        llm.get_llm()
    monkeypatch.setattr(
        llm,
        "CONFIG",
        dataclasses.replace(
            base,
            llm_mode="openai",
            llm_api_key="sk-test",
            llm_model="",
        ),
    )
    with pytest.raises(RuntimeError, match="configuration unavailable"):
        llm.get_llm()
    # openai mode WITH key -> real client (constructed offline, no network call)
    monkeypatch.setattr(llm, "CONFIG",
                        dataclasses.replace(base, llm_mode="openai",
                                            llm_api_key="sk-test",
                                            llm_model="ep-test"))
    assert isinstance(llm.get_llm(), llm.OpenAICompatLLM)


class _ErrResp:
    def __init__(self, payload, raises=False):
        self._p = payload; self._raises = raises
    def raise_for_status(self):
        if self._raises:
            raise RuntimeError("HTTP 429 rate limited")
    def json(self):
        if self._p is _BAD:
            raise ValueError("not json")
        return self._p


_BAD = object()


class _ErrClient:
    def __init__(self, resp): self._resp = resp
    def post(self, url, json): return self._resp


def _llm_with(resp):
    o = llm.OpenAICompatLLM.__new__(llm.OpenAICompatLLM)
    o._client = _ErrClient(resp); o._httpx = None
    return o


def test_llm_degrades_on_malformed_responses():
    """Rate-limit / empty choices / non-JSON must degrade to a safe placeholder,
    never raise (which would crash the whole debate)."""
    for resp in (_ErrResp({"choices": []}),                  # empty choices
                 _ErrResp({}),                               # no choices key
                 _ErrResp(_BAD),                             # non-JSON body
                 _ErrResp({}, raises=True)):                 # HTTP error
        o = _llm_with(resp)
        out = o.argue(side="bull", symbol="600519.SH", evidence=[])
        assert isinstance(out, str) and out                 # got a placeholder, no crash


def test_llm_failure_returns_structured_fallback_without_fake_numbers():
    o = _llm_with(_ErrResp({}, raises=True))
    text = o.argue(side="bull", symbol="600519.SH", evidence=[])

    assert "模型说明暂不可用" in text
    assert not any(ch.isdigit() for ch in text)


def test_mock_and_openai_share_the_same_method_surface():
    """Both backends expose the same methods used by the agents."""
    for name in ("argue", "argue_stream", "audit_reason", "chair_line"):
        assert callable(getattr(llm.MockLLM, name))
        assert callable(getattr(llm.OpenAICompatLLM, name))
