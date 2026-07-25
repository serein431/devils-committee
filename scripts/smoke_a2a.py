#!/usr/bin/env python3
"""Check the public A2A surface without printing credentials or response bodies."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit


REQUEST_TIMEOUT = 610
DEFAULT_TICKER = "600519.SH"
REQUIRED_SKILL_IDS = {
    "skill-corporate-action-adjustment-auditor",
    "skill-survivorship-universe-auditor",
    "skill-portfolio-liquidity-stress-test",
    "skill-index-rebalance-event-study",
    "skill-factor-ranking-sage",
    "skill-model-hpo-evidence-driven",
}

_TTY = sys.stdout.isatty()


def _c(code: str, value: str) -> str:
    return f"\033[{code}m{value}\033[0m" if _TTY else value


def _ok(value: str) -> str:
    return _c("32", value)


def _bad(value: str) -> str:
    return _c("1;31", value)


def _dim(value: str) -> str:
    return _c("2", value)


RESULTS: list[tuple[bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, name))
    tag = _ok("PASS") if ok else _bad("FAIL")
    suffix = _dim(f"  — {detail}") if detail else ""
    print(f"  [{tag}] {name}{suffix}")


def _req(
    url: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    token: str | None = None,
    timeout: int = REQUEST_TIMEOUT,
    accept: str = "application/json",
) -> tuple[int, str]:
    headers = {"Content-Type": "application/json", "Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def _target_name(url: str) -> str:
    parts = urlsplit(url)
    return parts.hostname or "invalid-host"


def _research_body(ticker: str, *, skill: str = "debate_case") -> dict:
    if re.fullmatch(r"[0-9]{6}\.(?:SH|SZ)", ticker.upper()):
        symbol = ticker.upper()
        return {
            "skill": skill,
            "symbol": symbol,
            "question": f"研究 {symbol} 的多空证据和风险",
            "start_date": "20240101",
            "end_date": "20260724",
        }
    return {"skill": skill, "topic": ticker}


def _v1_body(method: str, research: dict, request_id: str) -> dict:
    metadata = dict(research)
    skill = metadata.pop("skill", "debate_case")
    text = metadata.get("question") or metadata.get("topic") or ""
    metadata["skill"] = skill
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {
            "message": {
                "messageId": f"message-{request_id}",
                "role": "ROLE_USER",
                "parts": [{"text": text}],
            },
            "metadata": metadata,
        },
    }


def _task_payload(task: dict) -> dict:
    return task["artifacts"][0]["parts"][0]["data"]


def _sse_events(body: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data:").strip())
        for line in body.splitlines()
        if line.startswith("data:")
    ]


def main() -> int:
    RESULTS.clear()
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument(
        "--token",
        default=os.environ.get("A2A_BEARER_TOKEN"),
        help="bearer token; prefer A2A_BEARER_TOKEN",
    )
    parser.add_argument("--ticker", default=DEFAULT_TICKER)
    args = parser.parse_args()
    base = args.url.rstrip("/")
    print(f"\nA2A smoke test → {_target_name(base)}\n")

    health_modes: dict = {}
    live_cli = False

    try:
        status, body = _req(f"{base}/healthz")
        payload = json.loads(body)
        health_modes = payload.get("modes", {})
        if not isinstance(health_modes, dict):
            health_modes = {}
        live_cli = (
            health_modes.get("data_mode") == "panda"
            and health_modes.get("skill_mode") == "cli"
        )
        safe_modes = {
            key: health_modes.get(key)
            for key in ("llm_mode", "data_mode", "skill_mode")
        }
        check(
            "GET /healthz 200 + ok",
            status == 200 and payload.get("ok") is True,
            f"modes={safe_modes}",
        )
    except Exception as exc:
        check("GET /healthz", False, type(exc).__name__)

    try:
        status, body = _req(f"{base}/.well-known/agent-card.json")
        card = json.loads(body)
        ids = {
            item.get("id")
            for item in card.get("skills", [])
            if isinstance(item, dict)
        }
        check("GET agent-card 200", status == 200)
        interfaces = card.get("supportedInterfaces", [])
        preferred = interfaces[0] if interfaces else {}
        check("agent-card uses A2A v1 JSONRPC", (
            preferred.get("url", "").endswith("/a2a")
            and preferred.get("protocolBinding") == "JSONRPC"
            and preferred.get("protocolVersion") == "1.0"
        ))
        check("agent-card advertises both skills", {"debate_case", "audit_claims"} <= ids)
        check(
            "agent-card streaming:true",
            card.get("capabilities", {}).get("streaming") is True,
        )
        has_security = bool(card.get("securityRequirements"))
        check(
            "agent-card auth matches health",
            has_security == (health_modes.get("auth") == "on"),
        )
    except Exception as exc:
        check("GET agent-card", False, type(exc).__name__)

    debate_body = _research_body(args.ticker)
    try:
        status, body = _req(
            f"{base}/a2a",
            method="POST",
            token=args.token,
            body=_v1_body("SendMessage", debate_body, "smoke-send"),
        )
        response = json.loads(body)
        task = response["result"]["task"]
        result = _task_payload(task)
        meta = result.get("meta", {})
        manifest = meta.get("skills_manifest", {})
        results = manifest.get("results", [])
        all_skills = set(manifest.get("all_skills", []))
        check("SendMessage returns completed Task", (
            status == 200
            and task.get("status", {}).get("state") == "TASK_STATE_COMPLETED"
        ))
        check(
            "debate data_status success",
            meta.get("data_status") == "success",
            f"symbol={meta.get('symbol', 'unknown')}",
        )
        check("debate carries disclaimer", bool(result.get("disclaimer")))
        elapsed = result.get("elapsed_sec")
        check(
            "research stays inside 10-minute budget",
            isinstance(elapsed, (int, float)) and elapsed <= 600,
            f"elapsed={elapsed}",
        )
        check("all six skill ids are present", all_skills == REQUIRED_SKILL_IDS)
        check(
            "skills_manifest uses structured results",
            isinstance(results, list)
            and all(isinstance(item, dict) and item.get("skill_id") for item in results),
        )
        if live_cli:
            check(
                "no mock result in live smoke",
                len(results) == len(REQUIRED_SKILL_IDS)
                and all(item.get("mode") != "mock" for item in results),
            )
        task_id = task["id"]
        get_status, get_body = _req(
            f"{base}/a2a",
            method="POST",
            token=args.token,
            body={
                "jsonrpc": "2.0",
                "id": "smoke-get",
                "method": "GetTask",
                "params": {"id": task_id, "historyLength": 1},
            },
        )
        stored = json.loads(get_body).get("result", {})
        check("GetTask retrieves completed Task", (
            get_status == 200
            and stored.get("id") == task_id
            and stored.get("status", {}).get("state") == "TASK_STATE_COMPLETED"
        ))
    except Exception as exc:
        check("SendMessage debate_case", False, type(exc).__name__)

    try:
        status, body = _req(
            f"{base}/a2a",
            method="POST",
            token=args.token,
            body=_v1_body(
                "SendMessage",
                _research_body(args.ticker, skill="audit_claims"),
                "smoke-audit",
            ),
        )
        payload = json.loads(body)
        task = payload.get("result", {}).get("task", {})
        audit = _task_payload(task)
        check(
            "SendMessage audit_claims completed",
            status == 200
            and task.get("status", {}).get("state") == "TASK_STATE_COMPLETED",
        )
        check(
            "audit_claims returns verdict list",
            isinstance(audit.get("audits"), list),
        )
    except Exception as exc:
        check("POST audit_claims", False, type(exc).__name__)

    try:
        boundary = _research_body("研究 TSLA 的流动性风险")
        status, body = _req(
            f"{base}/a2a",
            method="POST",
            token=args.token,
            body=_v1_body("SendStreamingMessage", boundary, "smoke-stream"),
            accept="text/event-stream",
        )
        events = _sse_events(body)
        first_task = events[0]["result"]["task"] if events else {}
        statuses = [
            event["result"]["statusUpdate"]["status"]["state"]
            for event in events
            if "statusUpdate" in event.get("result", {})
        ]
        check("SendStreamingMessage emits Task lifecycle", (
            status == 200
            and first_task.get("status", {}).get("state") == "TASK_STATE_SUBMITTED"
            and "TASK_STATE_WORKING" in statuses
            and statuses[-1:] == ["TASK_STATE_COMPLETED"]
        ))
    except Exception as exc:
        check("SendStreamingMessage", False, type(exc).__name__)

    if args.token:
        try:
            status, _ = _req(
                f"{base}/a2a",
                method="POST",
                body=_v1_body("SendMessage", debate_body, "smoke-auth"),
            )
            check("auth: 401 without token", status == 401, f"status={status}")
        except Exception as exc:
            check("auth check", False, type(exc).__name__)

    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print()
    if passed == total:
        print(_ok(f"all {total} checks passed"))
        return 0
    print(_bad(f"{total - passed}/{total} checks failed:"))
    for ok, name in RESULTS:
        if not ok:
            print(_bad(f"    - {name}"))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
