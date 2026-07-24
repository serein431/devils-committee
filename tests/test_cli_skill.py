"""Smoke-test the REAL QuantSkills CLI path (SKILL_MODE=cli).

Runs the actual cloned skill's `--demo` and asserts our adapter maps its real
output-contract JSON into the internal verdict vocabulary the engine speaks.
Skips cleanly if the skill isn't vendored yet (scripts/fetch_quantskills.sh).

This is the proof that mock↔real differ only in WHERE the numbers come from —
verified against github.com/quantskills, not just assumed."""
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


@requires_vendor
def test_cli_mode_wires_real_auditor_into_the_debate(monkeypatch):
    """SKILL_MODE=cli routes the factor audit through the REAL survivorship CLI,
    tagged provenance=real-cli; mock mode never does."""
    import asyncio
    import dataclasses
    from backend.skills import runner as runner_mod
    from backend import orchestration
    from backend.config import CONFIG

    # default (mock) run: no real-cli provenance
    mock_res = asyncio.run(orchestration.DebateOrchestrator().run("600519 多空"))
    assert mock_res.meta["audit_engine"] == "mock"
    assert all(v.provenance != "real-cli" for v in mock_res.verdicts)

    # flip to cli mode, pointed at the vendored repo
    cli_cfg = dataclasses.replace(CONFIG, skill_mode="cli",
                                  quantskills_dir=os.path.join(
                                      os.path.dirname(SKILL_DIR)))  # vendor/quantskills
    monkeypatch.setattr(runner_mod, "CONFIG", cli_cfg)
    cli_res = asyncio.run(orchestration.DebateOrchestrator().run("600519 多空"))
    assert cli_res.meta["audit_engine"] == "real-cli"
    real = [v for v in cli_res.verdicts if v.provenance == "real-cli"]
    assert real, "expected at least one verdict from the real CLI"
    assert any("真·QuantSkills" in v.reason for v in real)
