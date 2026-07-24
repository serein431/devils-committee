#!/usr/bin/env python3
"""A2A external-surface smoke test — run against a LIVE server before judging.

Unlike the pytest suite (in-process TestClient), this hits real HTTP so you can
point it at your public Cloudflare-Tunnel / VPS URL and confirm the exact surface
a PandaAI judge will call is green: health, Agent Card, both advertised skills,
SSE streaming, and (optionally) bearer auth.

    python scripts/smoke_a2a.py                              # localhost:8080
    python scripts/smoke_a2a.py --url https://your-host      # public URL
    python scripts/smoke_a2a.py --url https://your-host --token SECRET

Exit code 0 = all green (ready to be judged); non-zero = something a judge could hit.
Only stdlib — copy it anywhere, no install.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import urllib.error

_TTY = sys.stdout.isatty()
def _c(code, s): return f"\033[{code}m{s}\033[0m" if _TTY else s
OKG = lambda s: _c("32", s)
BAD = lambda s: _c("1;31", s)
DIM = lambda s: _c("2", s)

RESULTS: list[tuple[bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, name))
    tag = OKG("PASS") if ok else BAD("FAIL")
    print(f"  [{tag}] {name}" + (DIM(f"  — {detail}") if detail else ""))


def _req(url: str, *, method="GET", body=None, token=None, timeout=1230):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8080")
    ap.add_argument("--token", default=None, help="bearer token if auth is on")
    ap.add_argument("--ticker", default="600519 多空双方与风险")
    args = ap.parse_args()
    base = args.url.rstrip("/")
    print(f"\nA2A smoke test → {base}\n")

    # 1) health
    try:
        st, body = _req(f"{base}/healthz")
        j = json.loads(body)
        check("GET /healthz 200 + ok", st == 200 and j.get("ok") is True, f"modes={j.get('modes',{})}")
    except Exception as e:
        check("GET /healthz", False, str(e)[:120])

    # 2) agent card
    try:
        st, body = _req(f"{base}/.well-known/agent-card.json")
        card = json.loads(body)
        ids = {s["id"] for s in card.get("skills", [])}
        check("GET agent-card 200", st == 200)
        check("agent-card url points to /a2a", card.get("url", "").endswith("/a2a"), card.get("url", ""))
        check("agent-card advertises both skills", {"debate_case", "audit_claims"} <= ids, str(sorted(ids)))
        check("agent-card streaming:true", card.get("capabilities", {}).get("streaming") is True)
    except Exception as e:
        check("GET agent-card", False, str(e)[:120])

    # 3) debate_case
    try:
        st, body = _req(f"{base}/a2a", method="POST", token=args.token,
                        body={"skill": "debate_case", "topic": args.ticker})
        r = json.loads(body)["result"]
        check("POST debate_case 200", st == 200)
        check("debate has 4 claims", r["meta"]["n_claims"] == 4, f"symbol={r['meta']['symbol']}")
        check("debate carries disclaimer", bool(r["disclaimer"]))
        check("debate <= 20 min budget", r["elapsed_sec"] <= 20 * 60, f"{r['elapsed_sec']}s")
        check("skills_manifest present", bool(r["meta"].get("skills_manifest", {}).get("all_skills")))
    except Exception as e:
        check("POST debate_case", False, str(e)[:150])

    # 4) audit_claims
    try:
        st, body = _req(f"{base}/a2a", method="POST", token=args.token,
                        body={"skill": "audit_claims", "topic": args.ticker})
        r = json.loads(body)
        check("POST audit_claims 200", st == 200 and r.get("skill") == "audit_claims")
        check("audit_claims returns per-claim verdicts", len(r["result"]["audits"]) == 4)
    except Exception as e:
        check("POST audit_claims", False, str(e)[:150])

    # 5) SSE streaming
    try:
        st, body = _req(f"{base}/a2a?stream=1&pace=0", method="POST", token=args.token,
                        body={"topic": args.ticker})
        got_result = '"stage": "result"' in body or '"stage":"result"' in body
        check("POST ?stream=1 yields result event", st == 200 and got_result)
    except Exception as e:
        check("POST ?stream=1", False, str(e)[:150])

    # 6) auth (only if a token is configured on the server)
    if args.token:
        try:
            st, _ = _req(f"{base}/a2a", method="POST", body={"topic": args.ticker})  # no token
            check("auth: 401 without token", st == 401, f"got {st}")
        except Exception as e:
            check("auth check", False, str(e)[:120])

    # summary
    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print()
    if passed == total:
        print(OKG(f"✔ all {total} checks green — ready to be judged."))
        return 0
    print(BAD(f"✗ {total - passed}/{total} checks FAILED:"))
    for ok, name in RESULTS:
        if not ok:
            print(BAD(f"    - {name}"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
