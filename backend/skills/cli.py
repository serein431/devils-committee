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
from pathlib import Path
import subprocess
import sys
from typing import Any

# real status  ->  internal AuditStatus (models.AuditStatus)
_STATUS_MAP = {
    "pass": "pass",
    "fail": "selection_bias",            # survivorship auditor: proven issue found
    "warning": "thin_data",              # a concern, but not a proven bias
    "insufficient-evidence": "missing_evidence",
}
# real severity -> internal severity (models.AuditVerdict.severity)
_SEV_MAP = {"critical": "high", "high": "high", "medium": "medium",
            "low": "low", "info": "low", "none": "none"}


def invoke(
    skill_dir: str,
    entry: str,
    args: list[str],
    timeout: int = 120,
) -> dict[str, Any]:
    """Run one named skill entry and return its parsed JSON report."""
    skill_dir = os.path.abspath(skill_dir)
    script = os.path.join(skill_dir, "scripts", entry)
    if not os.path.isfile(script):
        raise RuntimeError("skill entry unavailable")
    out_path = args[args.index("--out") + 1] if "--out" in args else None
    try:
        proc = subprocess.run(
            [sys.executable, script, *args],
            cwd=skill_dir,
            capture_output=True,
            text=True,
            timeout=min(timeout, 120),
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("skill execution timed out") from exc
    if proc.returncode != 0:
        raise RuntimeError("skill command failed")
    raw = Path(out_path).read_text(encoding="utf-8") if out_path else proc.stdout
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("skill returned invalid JSON") from exc


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
