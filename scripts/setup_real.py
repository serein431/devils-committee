#!/usr/bin/env python3
"""Report whether the optional PandaAI runtime is ready without exposing secrets."""
from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
MODE_FLAG = {
    "llm": ("LLM_MODE", "openai"),
    "data": ("DATA_MODE", "panda"),
    "skill": ("SKILL_MODE", "cli"),
}
PANDA_KEYS = ("DEFAULT_USERNAME", "DEFAULT_PASSWORD", "JAVA_SERVICE_BASE_URL")
LLM_KEYS = ("LLM_API_KEY", "LLM_MODEL")
REPOS = (
    "skill-pandadata-api",
    "skill-corporate-action-adjustment-auditor",
    "skill-survivorship-universe-auditor",
    "skill-portfolio-liquidity-stress-test",
    "skill-index-rebalance-event-study",
    "skill-factor-ranking-sage",
    "skill-model-hpo-evidence-driven",
)
PRECOMPUTED_SKILLS = (
    "skill-factor-ranking-sage",
    "skill-model-hpo-evidence-driven",
)
NUMERIC_DEFAULTS = {
    "LLM_TEMPERATURE": "0.2",
    "SKILL_TIMEOUT_SEC": "120",
    "REQUEST_BUDGET_SEC": "600",
    "PORT": "8080",
}
CONFIG_KEYS = set(
    LLM_KEYS
    + PANDA_KEYS
    + tuple(NUMERIC_DEFAULTS)
    + (
        "QUANTSKILLS_DIR",
        "PRECOMPUTED_DIR",
        "A2A_BEARER_TOKEN",
    )
)


def _read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    path = ENV if ENV.exists() else ENV_EXAMPLE
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = re.sub(r"\s+#.*$", "", value).strip().strip('"').strip("'")
    for key in set(values) | CONFIG_KEYS:
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def _ensure_env() -> None:
    if not ENV.exists():
        shutil.copyfile(ENV_EXAMPLE, ENV)
        print(".env: created")


def _set_flag(key: str, value: str) -> None:
    _ensure_env()
    lines = ENV.read_text(encoding="utf-8").splitlines()
    prefix = f"{key}="
    for index, line in enumerate(lines):
        if line.strip().startswith(prefix):
            lines[index] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{key}: present")


def _state(value: bool) -> str:
    return "present" if value else "missing"


def _configured_path(env: dict[str, str], key: str, default: str) -> Path:
    path = Path(env.get(key, default)).expanduser()
    return path if path.is_absolute() else ROOT / path


def _repo_root(env: dict[str, str]) -> Path:
    return _configured_path(env, "QUANTSKILLS_DIR", "./vendor/quantskills")


def _precomputed_root(env: dict[str, str]) -> Path:
    return _configured_path(env, "PRECOMPUTED_DIR", "./var/precomputed")


def _repository_ready(path: Path) -> bool:
    return (path / ".git").exists() and (path / "scripts").is_dir()


def _numeric_config_ready(env: dict[str, str]) -> bool:
    try:
        temperature = float(
            env.get("LLM_TEMPERATURE", NUMERIC_DEFAULTS["LLM_TEMPERATURE"])
        )
        skill_timeout = int(
            env.get("SKILL_TIMEOUT_SEC", NUMERIC_DEFAULTS["SKILL_TIMEOUT_SEC"])
        )
        request_budget = int(
            env.get("REQUEST_BUDGET_SEC", NUMERIC_DEFAULTS["REQUEST_BUDGET_SEC"])
        )
        port = int(env.get("PORT", NUMERIC_DEFAULTS["PORT"]))
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(temperature)
        and skill_timeout > 0
        and request_budget >= skill_timeout
        and 1 <= port <= 65535
    )


def _checks(env: dict[str, str]) -> dict[str, bool]:
    skill_root = _repo_root(env)
    precomputed_root = _precomputed_root(env)
    return {
        "python_3_12": sys.version_info[:2] == (3, 12),
        "ark_endpoint_id": bool(env.get("LLM_MODEL")),
        "llm_api_key": bool(env.get("LLM_API_KEY")),
        "panda_credentials": all(
            env.get(key) for key in ("DEFAULT_USERNAME", "DEFAULT_PASSWORD")
        ),
        "seven_skill_repositories": all(
            _repository_ready(skill_root / name)
            for name in REPOS
        ),
        "precomputed_manifests": all(
            (
                precomputed_root
                / name
                / "devils-committee-manifest.json"
            ).is_file()
            for name in PRECOMPUTED_SKILLS
        ),
        "numeric_configuration": _numeric_config_ready(env),
    }


def _report(env: dict[str, str]) -> dict[str, bool]:
    checks = _checks(env)
    for name, ready in checks.items():
        print(f"{name}: {_state(ready)}")

    # Keep the per-item report for diagnosing a partially fetched runtime. It
    # only reports state and never prints configured values or local paths.
    print(f"LLM_MODEL: {_state(bool(env.get('LLM_MODEL')))}")
    for key in PANDA_KEYS:
        print(f"{key}: {_state(bool(env.get(key)))}")
    qdir = _repo_root(env)
    for repo in REPOS:
        path = qdir / repo
        print(f"{repo}: {_state(_repository_ready(path))}")
    return checks


def _repo_ready(env: dict[str, str], repo: str) -> bool:
    return _repository_ready(_repo_root(env) / repo)


def _missing_prerequisites(modes: list[str], env: dict[str, str]) -> list[str]:
    missing: list[str] = []
    if "llm" in modes:
        missing.extend(key for key in LLM_KEYS if not env.get(key))
    if "data" in modes:
        missing.extend(key for key in PANDA_KEYS if not env.get(key))
    if "skill" in modes:
        if sys.version_info[:2] != (3, 12):
            missing.append("Python 3.12")
        missing.extend(repo for repo in REPOS if not _repo_ready(env, repo))
    return missing


def _probe(env: dict[str, str]) -> None:
    """Inspect local prerequisites only; no unauthenticated network probes."""
    try:
        import panda_data  # noqa: F401
        print("panda_data import: present")
    except Exception as exc:
        print(f"panda_data import: {type(exc).__name__}")
    print("LLM endpoint: not probed")
    print("PandaData endpoint: not probed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enable", nargs="*", choices=tuple(MODE_FLAG), default=[])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    env = _read_env()
    missing = _missing_prerequisites(args.enable, env)
    if missing:
        for item in missing:
            print(f"{item}: missing")
        return 2
    for mode in args.enable:
        _set_flag(*MODE_FLAG[mode])
    env = _read_env()
    _report(env)
    if args.check:
        _probe(env)
        # --check is a report: precomputed manifests are expected to be missing
        # before the documented precompute step runs.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
