"""Force the test suite to run fully offline in mock mode, regardless of a
developer's .env (which may point at real panda_data / DeepSeek credentials).

Set BEFORE backend.config is imported so its env-driven CONFIG reads these.
Tests that need a specific mode override CONFIG explicitly via monkeypatch."""
import os

os.environ["DATA_MODE"] = "mock"
os.environ["LLM_MODE"] = "mock"
os.environ["SKILL_MODE"] = "mock"
os.environ.pop("LLM_API_KEY", None)
