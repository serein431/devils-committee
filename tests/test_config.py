"""Lock down the .env parser. Regression: a .env copied verbatim from .env.example
keeps inline comments (`LLM_MODE=mock   # mock | openai`); if those aren't stripped
the value becomes 'mock   # ...' and, worse, `LLM_API_KEY=  # TODO` parses to the
string '# TODO' — a fake key that got sent to the LLM endpoint (real 401 seen)."""
import os
import tempfile

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
                "LLM_API_KEY=             # TODO(feishu)\n",
                ["LLM_MODE", "LLM_API_KEY"])
    assert got["LLM_MODE"] == "mock"        # not 'mock   # mock | openai'
    assert got["LLM_API_KEY"] == ""         # not '# TODO(feishu)'


def test_real_values_and_quotes_survive():
    got = _load('LLM_API_KEY="sk-abc123"\n'
                "LLM_BASE_URL=https://api.deepseek.com/v1\n",
                ["LLM_API_KEY", "LLM_BASE_URL"])
    assert got["LLM_API_KEY"] == "sk-abc123"
    assert got["LLM_BASE_URL"] == "https://api.deepseek.com/v1"   # no '#', untouched
