"""Tests for exact QuantSkills CLI entry selection and report parsing.

Runs the actual cloned skill's `--demo` and asserts our adapter maps its real
output-contract JSON into the internal verdict vocabulary the engine speaks.
Skips cleanly if the skill isn't vendored yet (scripts/fetch_quantskills.sh).

Vendored integration checks skip cleanly until the repositories are installed."""
import os

import pytest

from backend.skills import cli
from backend.models import AuditStatus  # noqa: F401  (documents the target vocab)

SKILL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "vendor", "quantskills", "skill-survivorship-universe-auditor")

requires_vendor = pytest.mark.skipif(
    not os.path.isdir(os.path.join(SKILL_DIR, "scripts")),
    reason="real skill not vendored — run scripts/fetch_quantskills.sh")


@requires_vendor
def test_real_survivorship_demo_runs_and_reports():
    real = cli.invoke(SKILL_DIR, "audit_universe.py", ["--demo"], timeout=120)
    assert real["status"] in ("pass", "fail", "warning", "insufficient-evidence")
    assert "findings" in real and isinstance(real["findings"], list)


@requires_vendor
def test_adapter_maps_real_output_into_internal_vocab():
    real = cli.invoke(SKILL_DIR, "audit_universe.py", ["--demo"], timeout=120)
    mapped = cli.to_verdict_fields(real)
    assert mapped["status"] in ("pass", "suspected_overfit", "selection_bias",
                                "bad_data", "thin_data")
    assert mapped["severity"] in ("none", "low", "medium", "high")
    assert isinstance(mapped["reason"], str) and mapped["reason"]
    # the built-in demo has known survivorship problems -> must NOT map to a clean pass
    if real["status"] == "fail":
        assert mapped["status"] != "pass"
        assert mapped["severity"] in ("low", "medium", "high")


def test_exact_entry_is_used(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "audit_universe.py").write_text(
        'print(\'{"status": "pass", "findings": []}\')\n',
        encoding="utf-8",
    )
    (scripts / "another.py").write_text(
        'print(\'{"status": "fail", "findings": []}\')\n',
        encoding="utf-8",
    )

    result = cli.invoke(str(tmp_path), "audit_universe.py", ["--demo"])

    assert result["status"] == "pass"


def test_missing_entry_is_rejected_without_guessing(tmp_path):
    (tmp_path / "scripts").mkdir()
    with pytest.raises(RuntimeError, match="skill entry unavailable"):
        cli.invoke(str(tmp_path), "audit_universe.py", ["--demo"], timeout=120)
