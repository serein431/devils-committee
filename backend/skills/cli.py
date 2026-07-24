"""Real QuantSkills CLI adapter (SKILL_MODE=cli).

Verified against the REAL cloned repos on 2026-07-23 by running their `--demo`:
the audit skills emit a JSON report per `references/output-contract.md`:

    { "status": "pass|fail|warning|insufficient-evidence",
      "findings": [ {"id","severity","evidence","impact","recommended_fix"} ],
      "limitations": [...], "next_actions": [...], "metrics": {...} }

`invoke()` runs a skill CLI; `to_verdict_fields()` maps that real report into the
internal vocabulary the AuditAgent already speaks (status / severity / reason /
remediation) — so switching mock -> cli changes only where the numbers come from.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

# real status  ->  internal AuditStatus (models.AuditStatus)
_STATUS_MAP = {
    "pass": "pass",
    "fail": "selection_bias",            # survivorship auditor: proven issue found
    "warning": "thin_data",              # a concern, but not a proven bias
    "insufficient-evidence": "thin_data",  # never write missing evidence up as pass
}
# real severity -> internal severity (models.AuditVerdict.severity)
_SEV_MAP = {"critical": "high", "high": "high", "medium": "medium",
            "low": "low", "info": "low", "none": "none"}


def invoke(skill_dir: str, args: list[str], timeout: int = 180) -> dict[str, Any]:
    """Run a cloned skill CLI and return its parsed JSON report.

    args e.g. ["--demo"]  or  ["--input", csv_path, "--out", out_path].
    Locates the single .py entry under scripts/. Raises on non-zero exit.
    """
    skill_dir = os.path.abspath(skill_dir)      # robust when cwd is set below
    scripts = os.path.join(skill_dir, "scripts")
    entry = next((f for f in sorted(os.listdir(scripts)) if f.endswith(".py")), None)
    if entry is None:
        raise RuntimeError(f"no CLI entry under {scripts}")
    # Prefer explicit --out to stdout capture (some skills print progress on stdout).
    out_path = None
    if "--out" in args:
        out_path = args[args.index("--out") + 1]
    proc = subprocess.run(
        [sys.executable, os.path.join(scripts, entry), *args],
        cwd=skill_dir, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"{entry} exited {proc.returncode}: {proc.stderr[:400]}")
    raw = open(out_path, encoding="utf-8").read() if out_path else proc.stdout
    return json.loads(raw)


def to_verdict_fields(real: dict[str, Any]) -> dict[str, Any]:
    """Map a real audit report -> {status, severity, reason, remediation, detail}."""
    status = _STATUS_MAP.get(real.get("status", ""), "thin_data")
    findings = real.get("findings", []) or []
    # worst severity present
    order = ["info", "low", "medium", "high", "critical"]
    worst = max((f.get("severity", "info") for f in findings),
                key=lambda s: order.index(s) if s in order else -1, default="none")
    severity = _SEV_MAP.get(worst, "none")
    reasons = []
    for f in findings[:3]:
        ev = f.get("evidence", {})
        rs = "、".join(ev.get("reasons", [])) if isinstance(ev, dict) else ""
        sym = ev.get("symbol", "") if isinstance(ev, dict) else ""
        reasons.append(f"{sym}: {rs}".strip(": ") or f.get("impact", "issue"))
    reason = "；".join(r for r in reasons if r) or "审计报告未附可定位证据"
    remediation = (findings[0].get("recommended_fix")
                   if findings else "") or "；".join(real.get("next_actions", [])[:2])
    return {"status": status, "severity": severity, "reason": reason,
            "remediation": remediation, "detail": real}
