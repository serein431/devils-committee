#!/usr/bin/env python3
"""Report whether the optional PandaAI runtime is ready without exposing secrets."""
from __future__ import annotations

import argparse
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
CONFIG_KEYS = set(LLM_KEYS + PANDA_KEYS + ("QUANTSKILLS_DIR",))


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


def _report(env: dict[str, str]) -> None:
    print(f"Python 3.12: {_state(sys.version_info[:2] == (3, 12))}")
    print(f"LLM_MODEL: {_state(bool(env.get('LLM_MODEL')))}")
    for key in PANDA_KEYS:
        print(f"{key}: {_state(bool(env.get(key)))}")
    qdir = Path(env.get("QUANTSKILLS_DIR", "./vendor/quantskills"))
    if not qdir.is_absolute():
        qdir = ROOT / qdir
    for repo in REPOS:
        path = qdir / repo
        print(f"{repo}: {_state((path / '.git').is_dir() and (path / 'scripts').is_dir())}")


def _repo_ready(env: dict[str, str], repo: str) -> bool:
    qdir = Path(env.get("QUANTSKILLS_DIR", "./vendor/quantskills"))
    if not qdir.is_absolute():
        qdir = ROOT / qdir
    path = qdir / repo
    return (path / ".git").is_dir() and (path / "scripts").is_dir()


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
