"""Runtime configuration sourced from environment variables."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from math import isfinite


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
            val = re.sub(r"\s+#.*$", "", val).strip()
            key, val = key.strip(), val.strip('"').strip("'")
            os.environ.setdefault(key, val)


_load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    raw = _env(key, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc


def _env_float(key: str, default: float) -> float:
    raw = _env(key, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be a finite number") from exc
    if not isfinite(value):
        raise ValueError(f"{key} must be a finite number")
    return value


@dataclass(frozen=True)
class Config:
    # Modes remain offline by default.
    llm_mode: str = field(default_factory=lambda: _env("LLM_MODE", "mock"))
    skill_mode: str = field(default_factory=lambda: _env("SKILL_MODE", "mock"))
    data_mode: str = field(default_factory=lambda: _env("DATA_MODE", "mock"))

    # LLM service.
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "volcengine-ark"))
    llm_base_url: str = field(
        default_factory=lambda: _env("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    )
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL"))
    llm_model_label: str = field(default_factory=lambda: _env("LLM_MODEL_LABEL", "DeepSeek V4 Pro"))
    llm_temperature: float = field(default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.2))

    # PandaData service.
    panda_username: str = field(default_factory=lambda: _env("DEFAULT_USERNAME"))
    panda_password: str = field(default_factory=lambda: _env("DEFAULT_PASSWORD"))
    panda_base_url: str = field(
        default_factory=lambda: _env("JAVA_SERVICE_BASE_URL", "http://pandadata.pandaaiquant.com")
    )
    panda_state_dir: str = field(
        default_factory=lambda: _env("PANDA_STATE_DIR", "./var/panda")
    )

    # Local data and QuantSkills resources.
    quantskills_dir: str = field(default_factory=lambda: _env("QUANTSKILLS_DIR", "./vendor/quantskills"))
    precomputed_dir: str = field(default_factory=lambda: _env("PRECOMPUTED_DIR", "./var/precomputed"))
    cache_dir: str = field(default_factory=lambda: _env("CACHE_DIR", "./var/cache"))
    data_version: str = field(
        default_factory=lambda: _env("DATA_VERSION", "panda-2026-07-evidence-v2")
    )
    build_commit: str = field(default_factory=lambda: _env("BUILD_COMMIT"))
    precomputed_commit: str = field(
        default_factory=lambda: _env("PRECOMPUTED_COMMIT")
    )
    skill_timeout_sec: int = field(default_factory=lambda: _env_int("SKILL_TIMEOUT_SEC", 120))
    request_budget_sec: int = field(default_factory=lambda: _env_int("REQUEST_BUDGET_SEC", 600))

    # Serving.
    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8080))
    public_url: str = field(default_factory=lambda: _env("PUBLIC_URL", "http://localhost:8080"))
    repository_url: str = field(
        default_factory=lambda: _env("REPOSITORY_URL", "https://github.com/serein431/devils-committee")
    )
    bearer_token: str = field(default_factory=lambda: _env("A2A_BEARER_TOKEN"))

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("PORT must be between 1 and 65535")
        if self.skill_timeout_sec <= 0:
            raise ValueError("SKILL_TIMEOUT_SEC must be greater than zero")
        if self.request_budget_sec <= 0:
            raise ValueError("REQUEST_BUDGET_SEC must be greater than zero")
        if self.request_budget_sec < self.skill_timeout_sec:
            raise ValueError("REQUEST_BUDGET_SEC must cover SKILL_TIMEOUT_SEC")
        if not isfinite(self.llm_temperature):
            raise ValueError("LLM_TEMPERATURE must be a finite number")

    @property
    def real_llm_ready(self) -> bool:
        return (
            self.llm_mode == "openai"
            and bool(self.llm_model.strip())
            and bool(self.llm_api_key.strip())
        )

    def summary(self) -> dict[str, str | int]:
        """Return non-sensitive state suitable for status endpoints."""
        return {
            "llm_mode": self.llm_mode,
            "skill_mode": self.skill_mode,
            "data_mode": self.data_mode,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model_label if self.llm_mode != "mock" else "(mock)",
            "auth": "on" if self.bearer_token else "off (dev)",
            "public_url": self.public_url,
            "skill_timeout_sec": self.skill_timeout_sec,
            "request_budget_sec": self.request_budget_sec,
        }


CONFIG = Config()
