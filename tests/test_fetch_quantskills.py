"""Offline failure-path checks for the QuantSkills fetch script."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "fetch_quantskills.sh"
REPOS = (
    "skill-pandadata-api",
    "skill-corporate-action-adjustment-auditor",
    "skill-survivorship-universe-auditor",
    "skill-portfolio-liquidity-stress-test",
    "skill-factor-ranking-sage",
    "skill-model-hpo-evidence-driven",
)


def test_fetch_reports_a_failed_update_after_trying_every_repo(tmp_path):
    dest = tmp_path / "quantskills"
    for repo in REPOS:
        (dest / repo / ".git").mkdir(parents=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "git.log"
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$FAKE_GIT_LOG\"\n"
        "case \"$*\" in *skill-factor-ranking-sage*) exit 1;; esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    env = os.environ | {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "REPOSITORY_ROOT": str(tmp_path),
        "QUANTSKILLS_DIR": str(dest),
        "FAKE_GIT_LOG": str(log),
    }

    result = subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True)

    assert result.returncode == 1
    assert "skill-factor-ranking-sage update failed" in result.stderr
    assert len(log.read_text(encoding="utf-8").splitlines()) == len(REPOS)


def test_fetch_updates_checked_out_submodules_instead_of_cloning(tmp_path):
    dest = tmp_path / "quantskills"
    for repo in REPOS:
        path = dest / repo
        path.mkdir(parents=True)
        (path / ".git").write_text("gitdir: ../../.git/modules/example\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "git.log"
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$FAKE_GIT_LOG\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    env = os.environ | {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "REPOSITORY_ROOT": str(tmp_path),
        "QUANTSKILLS_DIR": str(dest),
        "FAKE_GIT_LOG": str(log),
    }

    result = subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True)

    assert result.returncode == 0
    calls = log.read_text(encoding="utf-8").splitlines()
    assert len(calls) == len(REPOS)
    assert all(call.startswith("-C ") and call.endswith(" pull --quiet") for call in calls)


def test_fetch_initializes_declared_submodules_before_updating(tmp_path):
    root = tmp_path / "project"
    dest = root / "vendor" / "quantskills"
    root.mkdir()
    (root / ".gitmodules").write_text("[submodule \"example\"]\n", encoding="utf-8")
    for repo in REPOS:
        path = dest / repo
        path.mkdir(parents=True)
        (path / ".git").write_text("gitdir: ../../.git/modules/example\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "git.log"
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$FAKE_GIT_LOG\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    env = os.environ | {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "REPOSITORY_ROOT": str(root),
        "QUANTSKILLS_DIR": str(dest),
        "FAKE_GIT_LOG": str(log),
    }

    result = subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True)

    assert result.returncode == 0
    calls = log.read_text(encoding="utf-8").splitlines()
    assert calls[0] == f"-C {root} submodule update --init --recursive"
    assert len(calls) == len(REPOS) + 1
