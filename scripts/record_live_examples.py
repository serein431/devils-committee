#!/usr/bin/env python3
"""Call the A2A service and save privacy-safe records for three A shares."""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx


REPO_ROOT = Path(__file__).resolve().parent.parent
RECORDS_ROOT = REPO_ROOT / "var" / "live-records"
REQUEST_TIMEOUT = 610.0
SYMBOL_TOPICS = {
    "600519.SH": "研究 600519.SH 的复权、分红、因子和流动性风险",
    "300750.SZ": "研究 300750.SZ 的成长因子、波动、流动性和指数事件",
    "601318.SH": "研究 601318.SH 的分红、股票池和风险证据",
}
SKILL_IDS = (
    "skill-corporate-action-adjustment-auditor",
    "skill-survivorship-universe-auditor",
    "skill-portfolio-liquidity-stress-test",
    "skill-index-rebalance-event-study",
    "skill-factor-ranking-sage",
    "skill-model-hpo-evidence-driven",
)
SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "llm_api_key",
    "default_username",
    "default_password",
    "a2a_bearer_token",
    "proxy-authorization",
    "set-cookie",
    "x-api-key",
}
_SYMBOL = re.compile(r"^[0-9]{6}\.(?:SH|SZ)$")


def sanitize(value: Any) -> Any:
    """Recursively replace values belonging to sensitive keys."""
    if isinstance(value, dict):
        return {
            key: (
                "[redacted]"
                if str(key).lower() in SENSITIVE_KEYS
                else sanitize(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def _url_parts(value: str) -> SplitResult:
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError("URL must be an HTTP(S) service root without userinfo or query")
    return parts


def _a2a_url(value: str) -> str:
    parts = _url_parts(value)
    path = parts.path.rstrip("/")
    if path.endswith("/a2a"):
        endpoint_path = path
    else:
        endpoint_path = f"{path}/a2a" or "/a2a"
    return urlunsplit((parts.scheme, parts.netloc, endpoint_path, "", ""))


def _reject_symlinked_parents(path: Path) -> None:
    current = path
    root = REPO_ROOT.resolve()
    while True:
        if current.exists() and current.is_symlink():
            raise ValueError("live record path must not contain symlinks")
        if current == REPO_ROOT:
            break
        if current.parent == current:
            raise ValueError("live record path outside repository")
        current = current.parent
    try:
        path.resolve().relative_to(root)
    except (OSError, RuntimeError, ValueError):
        raise ValueError("live record path outside repository") from None


def _symbol_dir(symbol: str) -> Path:
    if _SYMBOL.fullmatch(symbol) is None:
        raise ValueError("invalid A-share symbol")
    _reject_symlinked_parents(RECORDS_ROOT)
    RECORDS_ROOT.mkdir(parents=True, exist_ok=True)
    directory = RECORDS_ROOT / symbol
    _reject_symlinked_parents(directory)
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("live record path must be a real directory")
    return directory


def _write_text(path: Path, text: str) -> None:
    if path.exists() and path.is_symlink():
        raise ValueError("live record file must not be a symlink")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        raise ValueError("live record file cannot be written safely") from None
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)


def _write_json(path: Path, value: Any) -> None:
    _write_text(
        path,
        json.dumps(sanitize(value), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
    )


def _result(response: dict[str, Any]) -> dict[str, Any]:
    result = response.get("result")
    return result if isinstance(result, dict) else {}


def _manifest(response: dict[str, Any]) -> dict[str, Any]:
    meta = _result(response).get("meta")
    if not isinstance(meta, dict):
        return {"all_skills": [], "results": []}
    manifest = meta.get("skills_manifest")
    return manifest if isinstance(manifest, dict) else {"all_skills": [], "results": []}


def _skill_statuses(manifest: dict[str, Any]) -> dict[str, str]:
    results = manifest.get("results")
    indexed = {
        str(item.get("skill_id")): str(item.get("status", "missing"))
        for item in results
        if isinstance(item, dict) and item.get("skill_id")
    } if isinstance(results, list) else {}
    return {skill_id: indexed.get(skill_id, "missing") for skill_id in SKILL_IDS}


def _data_mode(response: dict[str, Any], manifest: dict[str, Any]) -> str:
    data = manifest.get("data")
    if isinstance(data, dict) and data.get("mode"):
        return str(data["mode"])
    meta = _result(response).get("meta")
    if isinstance(meta, dict):
        result_data = meta.get("data")
        if isinstance(result_data, dict) and result_data.get("mode"):
            return str(result_data["mode"])
    return "unknown"


def write_record(
    symbol: str,
    request: dict[str, Any],
    response: dict[str, Any],
    *,
    base_url: str,
    recorded_at: str,
    elapsed_sec: float,
) -> None:
    """Write one sanitized request/response bundle under var/live-records."""
    directory = _symbol_dir(symbol)
    clean_request = sanitize(request)
    clean_response = sanitize(response)
    manifest = sanitize(_manifest(clean_response))
    statuses = _skill_statuses(manifest)
    hostname = _url_parts(base_url).hostname or "unknown"
    readme = [
        f"# {symbol} live A2A record",
        "",
        f"- UTC run time: {recorded_at}",
        f"- Service hostname: {hostname}",
        f"- Total elapsed: {elapsed_sec:.3f} seconds",
        f"- Data mode: {_data_mode(clean_response, manifest)}",
        "- Skill statuses:",
    ]
    readme.extend(f"  - {skill_id}: {statuses[skill_id]}" for skill_id in SKILL_IDS)
    readme.append("")

    _write_json(directory / "request.json", clean_request)
    _write_json(directory / "response.json", clean_response)
    _write_json(directory / "skills.json", manifest)
    _write_text(directory / "README.md", "\n".join(readme))


def _request_payload(symbol: str, topic: str) -> dict[str, Any]:
    return {
        "skill": "debate_case",
        "symbol": symbol,
        "question": topic,
        "start_date": "20240101",
        "end_date": "20260724",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default=os.environ.get("PUBLIC_URL", "http://127.0.0.1:8080"),
        help="A2A service root",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("A2A_BEARER_TOKEN"),
        help="optional bearer token; prefer A2A_BEARER_TOKEN",
    )
    args = parser.parse_args()
    try:
        endpoint = _a2a_url(args.url)
    except ValueError as exc:
        parser.error(str(exc))

    headers = {"Accept": "application/json"}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    successful = 0
    with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=False) as client:
        for symbol, topic in SYMBOL_TOPICS.items():
            request = _request_payload(symbol, topic)
            recorded_at = datetime.now(timezone.utc).isoformat()
            started = time.monotonic()
            ok = False
            try:
                http_response = client.post(endpoint, json=request, headers=headers)
                elapsed_sec = time.monotonic() - started
                try:
                    response = http_response.json()
                except (json.JSONDecodeError, ValueError):
                    response = {
                        "status_code": http_response.status_code,
                        "error": "non-json response",
                    }
                if not isinstance(response, dict):
                    response = {"status_code": http_response.status_code, "result": response}
                ok = http_response.status_code == 200
            except Exception as exc:
                elapsed_sec = time.monotonic() - started
                response = {"error": type(exc).__name__}

            write_record(
                symbol,
                request,
                response,
                base_url=args.url,
                recorded_at=recorded_at,
                elapsed_sec=elapsed_sec,
            )
            manifest = _manifest(response)
            if set(manifest.get("all_skills", [])) != set(SKILL_IDS):
                ok = False
            if any(mode == "mock" for mode in (
                str(item.get("mode"))
                for item in manifest.get("results", [])
                if isinstance(item, dict)
            )):
                ok = False
            print(f"{symbol}: {'recorded' if ok else 'failed'}")
            successful += int(ok)

    return 0 if successful == len(SYMBOL_TOPICS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
