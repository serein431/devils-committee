"""Offline checks for the real-runtime setup helper."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup_real.py"
SPEC = importlib.util.spec_from_file_location("setup_real_under_test", SCRIPT)
assert SPEC and SPEC.loader
setup_real = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup_real)


def _configure_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(setup_real, "ROOT", tmp_path)
    monkeypatch.setattr(setup_real, "ENV", tmp_path / ".env")
    monkeypatch.setattr(setup_real, "ENV_EXAMPLE", tmp_path / ".env.example")
    (tmp_path / ".env.example").write_text("LLM_MODE=mock\n", encoding="utf-8")


def test_enable_rejects_missing_prerequisites_without_creating_env(monkeypatch, tmp_path, capsys):
    _configure_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["setup_real.py", "--enable", "llm"])

    assert setup_real.main() == 2
    assert not (tmp_path / ".env").exists()
    assert "LLM_MODEL" in capsys.readouterr().out


def test_enable_writes_only_after_all_requested_prerequisites_pass(monkeypatch, tmp_path):
    _configure_paths(monkeypatch, tmp_path)
    repo_dir = tmp_path / "vendor" / "quantskills"
    for repo in setup_real.REPOS:
        (repo_dir / repo / ".git").mkdir(parents=True)
        (repo_dir / repo / "scripts").mkdir()
    (tmp_path / ".env.example").write_text(
        "LLM_API_KEY=key\nLLM_MODEL=ep-test\nDEFAULT_USERNAME=user\nDEFAULT_PASSWORD=password\n"
        "JAVA_SERVICE_BASE_URL=http://example.invalid\nQUANTSKILLS_DIR=./vendor/quantskills\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_real.sys, "version_info", (3, 12, 0, "final", 0))
    monkeypatch.setattr(sys, "argv", ["setup_real.py", "--enable", "llm", "data", "skill"])

    assert setup_real.main() == 0
    contents = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "LLM_MODE=openai" in contents
    assert "DATA_MODE=panda" in contents
    assert "SKILL_MODE=cli" in contents


def test_environment_credentials_override_file_and_are_redacted(monkeypatch, tmp_path, capsys):
    _configure_paths(monkeypatch, tmp_path)
    file_values = ("file-user-sentinel", "file-password-sentinel", "file-token-sentinel")
    env_values = ("env-user-sentinel", "env-password-sentinel", "env-token-sentinel")
    (tmp_path / ".env.example").write_text(
        "LLM_MODEL=file-model-sentinel\n"
        f"DEFAULT_USERNAME={file_values[0]}\n"
        f"DEFAULT_PASSWORD={file_values[1]}\n"
        f"A2A_BEARER_TOKEN={file_values[2]}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFAULT_USERNAME", env_values[0])
    monkeypatch.setenv("DEFAULT_PASSWORD", env_values[1])
    monkeypatch.setenv("A2A_BEARER_TOKEN", env_values[2])

    values = setup_real._read_env()
    assert values["DEFAULT_USERNAME"] == env_values[0]
    assert values["DEFAULT_PASSWORD"] == env_values[1]
    setup_real._report(values)
    output = capsys.readouterr().out

    assert "DEFAULT_USERNAME: present" in output
    assert "DEFAULT_PASSWORD: present" in output
    for sentinel in (*file_values, *env_values):
        assert sentinel not in output


def test_report_rejects_a_repository_directory_without_git_and_scripts(monkeypatch, tmp_path, capsys):
    _configure_paths(monkeypatch, tmp_path)
    repo = tmp_path / "vendor" / "quantskills" / setup_real.REPOS[0]
    repo.mkdir(parents=True)
    setup_real._report({"QUANTSKILLS_DIR": "./vendor/quantskills"})

    assert f"{setup_real.REPOS[0]}: missing" in capsys.readouterr().out
