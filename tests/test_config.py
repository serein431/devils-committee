"""Lock down the .env parser. Regression: a .env copied verbatim from .env.example
keeps inline comments (`LLM_MODE=mock   # mock | openai`); if those aren't stripped
the value becomes 'mock   # ...' and, worse, `LLM_API_KEY=  # TODO` parses to the
string '# TODO' — a fake key that got sent to the LLM endpoint (real 401 seen)."""
import os
import tempfile

import pytest

from backend import config


def _load(text: str, keys: list[str]) -> dict:
    d = tempfile.mkdtemp()
    p = os.path.join(d, ".env")
    open(p, "w", encoding="utf-8").write(text)
    for k in keys:
        os.environ.pop(k, None)
    config._load_dotenv(p)
    return {k: os.environ.get(k) for k in keys}


def test_inline_comments_are_stripped():
    got = _load("LLM_MODE=mock            # mock | openai\n"
                "LLM_API_KEY=             # intentionally blank\n",
                ["LLM_MODE", "LLM_API_KEY"])
    assert got["LLM_MODE"] == "mock"        # not 'mock   # mock | openai'
    assert got["LLM_API_KEY"] == ""


def test_real_values_and_quotes_survive():
    got = _load('LLM_API_KEY="sk-abc123"\n'
                "LLM_BASE_URL=https://example.invalid/v1\n",
                ["LLM_API_KEY", "LLM_BASE_URL"])
    assert got["LLM_API_KEY"] == "sk-abc123"
    assert got["LLM_BASE_URL"] == "https://example.invalid/v1"


def test_real_runtime_defaults_are_used_when_environment_is_empty(monkeypatch):
    for key in (
        "LLM_BASE_URL",
        "LLM_PROVIDER",
        "LLM_MODEL_LABEL",
        "JAVA_SERVICE_BASE_URL",
        "SKILL_TIMEOUT_SEC",
        "REQUEST_BUDGET_SEC",
    ):
        monkeypatch.delenv(key, raising=False)

    cfg = config.Config()

    assert cfg.llm_provider == "volcengine-ark"
    assert cfg.llm_base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert cfg.llm_model_label == "DeepSeek V4 Pro"
    assert cfg.panda_base_url == "http://pandadata.pandaaiquant.com"
    assert cfg.skill_timeout_sec == 120
    assert cfg.request_budget_sec == 600


def test_config_summary_never_contains_credentials():
    cfg = config.Config(
        llm_api_key="test-llm-secret",
        panda_username="test-panda-user",
        panda_password="test-panda-password",
        bearer_token="test-bearer-token",
    )

    summary = repr(cfg.summary())
    for secret in (
        cfg.llm_api_key,
        cfg.panda_username,
        cfg.panda_password,
        cfg.bearer_token,
    ):
        assert secret not in summary


def test_config_summary_uses_safe_model_label_for_mock_and_openai():
    mock_summary = config.Config(llm_mode="mock", llm_model="internal-model-id").summary()
    openai_summary = config.Config(llm_mode="openai", llm_model="internal-model-id").summary()

    assert mock_summary["llm_model"] == "(mock)"
    assert openai_summary["llm_model"] == "DeepSeek V4 Pro"
    assert "llm_model_label" not in mock_summary
    assert "llm_model_label" not in openai_summary


def test_openai_mode_requires_an_explicit_model_id():
    assert config.Config(llm_mode="openai", llm_model="").real_llm_ready is False
    assert config.Config(llm_mode="openai", llm_model="ep-test").real_llm_ready is True


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("PORT", "not-a-port"),
        ("PORT", "0"),
        ("PORT", "65536"),
        ("SKILL_TIMEOUT_SEC", "0"),
        ("REQUEST_BUDGET_SEC", "0"),
        ("LLM_TEMPERATURE", "nan"),
        ("LLM_TEMPERATURE", "inf"),
    ),
)
def test_invalid_numeric_values_fail_without_echoing_input(monkeypatch, key, value):
    monkeypatch.setenv(key, value)

    with pytest.raises(ValueError) as exc_info:
        config.Config()

    assert key in str(exc_info.value)
    assert value not in str(exc_info.value)


def test_request_budget_must_cover_skill_timeout(monkeypatch):
    monkeypatch.setenv("SKILL_TIMEOUT_SEC", "121")
    monkeypatch.setenv("REQUEST_BUDGET_SEC", "120")

    with pytest.raises(ValueError, match="REQUEST_BUDGET_SEC"):
        config.Config()
