"""Runtime configuration, driven entirely by environment variables.

Two big switches let the SAME code run today (offline demo) and later (real):
  - LLM_MODE   = "mock" | "openai"     (openai = any OpenAI-compatible, incl. DeepSeek)
  - SKILL_MODE = "mock" | "cli"        (cli = invoke real cloned QuantSkills CLIs)
  - DATA_MODE  = "mock" | "panda"      (panda = real panda_data + DuckDB cache)

Everything defaults to the fully-offline path so `python -m backend.a2a_server`
runs with zero external credentials. Fill .env from .env.example to go live.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass


def _load_dotenv(path: str = ".env") -> None:
    """Tiny zero-dependency .env loader (no python-dotenv needed)."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = re.sub(r"\s+#.*$", "", val).strip()   # strip inline comments
            key, val = key.strip(), val.strip('"').strip("'")
            os.environ.setdefault(key, val)


_load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


@dataclass(frozen=True)
class Config:
    # --- modes -------------------------------------------------------------
    llm_mode: str = _env("LLM_MODE", "mock")           # mock | openai
    skill_mode: str = _env("SKILL_MODE", "mock")       # mock | cli
    data_mode: str = _env("DATA_MODE", "mock")         # mock | panda

    # --- LLM (OpenAI-compatible; DeepSeek from the Feishu group) ------------
    llm_base_url: str = _env("LLM_BASE_URL", "https://api.deepseek.com/v1")
    llm_api_key: str = _env("LLM_API_KEY", "")
    llm_model: str = _env("LLM_MODEL", "deepseek-chat")
    llm_temperature: float = float(_env("LLM_TEMPERATURE", "0.6"))

    # --- panda_data (TODO(feishu): creds from the PandaAI group) ------------
    panda_username: str = _env("DEFAULT_USERNAME", "")
    panda_password: str = _env("DEFAULT_PASSWORD", "")
    panda_base_url: str = _env("JAVA_SERVICE_BASE_URL", "")

    # --- QuantSkills CLI mode ----------------------------------------------
    # Directory holding cloned skill-* repos when SKILL_MODE=cli.
    quantskills_dir: str = _env("QUANTSKILLS_DIR", "./vendor/quantskills")

    # --- serving / A2A ------------------------------------------------------
    host: str = _env("HOST", "0.0.0.0")
    port: int = int(_env("PORT", "8080"))
    public_url: str = _env("PUBLIC_URL", "http://localhost:8080")
    bearer_token: str = _env("A2A_BEARER_TOKEN", "")   # empty => auth disabled (dev)

    # --- caching ------------------------------------------------------------
    cache_dir: str = _env("CACHE_DIR", "./.cache")

    def summary(self) -> dict[str, str]:
        return {
            "llm_mode": self.llm_mode,
            "skill_mode": self.skill_mode,
            "data_mode": self.data_mode,
            "llm_model": self.llm_model if self.llm_mode != "mock" else "(mock)",
            "auth": "on" if self.bearer_token else "off (dev)",
            "public_url": self.public_url,
        }


CONFIG = Config()
