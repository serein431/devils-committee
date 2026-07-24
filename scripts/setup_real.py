#!/usr/bin/env python3
"""Flip from offline demo to REAL mode once the Feishu credentials arrive.

The 'last mile': after you get the DeepSeek key + panda_data creds + clone the
QuantSkills, this tells you exactly what's ready and switches the .env mode flags
for you. Idempotent and non-destructive (only touches LLM_MODE/DATA_MODE/SKILL_MODE
lines you ask it to).

    python scripts/setup_real.py                 # readiness report (no changes)
    python scripts/setup_real.py --check         # + live probes (LLM ping, imports)
    python scripts/setup_real.py --enable llm     # set LLM_MODE=openai in .env
    python scripts/setup_real.py --enable data skill

Only stdlib for the report; httpx (already a dep) is used for the optional LLM ping.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(ROOT, ".env")
ENV_EXAMPLE = os.path.join(ROOT, ".env.example")

_TTY = sys.stdout.isatty()
def _c(code, s): return f"\033[{code}m{s}\033[0m" if _TTY else s
OK = lambda s: _c("32", s); NO = lambda s: _c("33", s); DIM = lambda s: _c("2", s)

MODE_FLAG = {"llm": ("LLM_MODE", "openai"), "data": ("DATA_MODE", "panda"),
             "skill": ("SKILL_MODE", "cli")}


def _read_env() -> dict[str, str]:
    d: dict[str, str] = {}
    path = ENV if os.path.exists(ENV) else ENV_EXAMPLE
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                v = re.sub(r"\s+#.*$", "", v).strip().strip('"').strip("'")
                d[k.strip()] = v
    return d


def _ensure_env() -> None:
    if not os.path.exists(ENV):
        import shutil
        shutil.copy(ENV_EXAMPLE, ENV)
        print(DIM(f"created {ENV} from .env.example"))


def _set_flag(key: str, value: str) -> None:
    _ensure_env()
    lines = open(ENV, encoding="utf-8").read().splitlines()
    found = False
    for i, ln in enumerate(lines):
        if ln.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    open(ENV, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(OK(f"set {key}={value} in .env"))


def _report(env: dict[str, str]) -> None:
    print("\nReal-mode readiness (.env):\n")
    # LLM
    llm_ok = bool(env.get("LLM_API_KEY"))
    print(f"  LLM  (LLM_MODE={env.get('LLM_MODE','mock')})  "
          + (OK("key present") if llm_ok else NO("LLM_API_KEY missing — 飞书群 DeepSeek Key")))
    # DATA
    data_ok = all(env.get(k) for k in ("DEFAULT_USERNAME", "DEFAULT_PASSWORD", "JAVA_SERVICE_BASE_URL"))
    print(f"  DATA (DATA_MODE={env.get('DATA_MODE','mock')})  "
          + (OK("panda_data creds present") if data_ok
             else NO("panda_data creds missing — 飞书群账号/密码/base_url")))
    # SKILL
    qdir = env.get("QUANTSKILLS_DIR", "./vendor/quantskills")
    used = ["skill-survivorship-universe-auditor", "skill-corporate-action-adjustment-auditor"]
    have = [s for s in used if os.path.isdir(os.path.join(ROOT, qdir, s, "scripts"))]
    skill_ok = len(have) == len(used)
    print(f"  SKILL(SKILL_MODE={env.get('SKILL_MODE','mock')})  "
          + (OK(f"{len(have)}/{len(used)} auditors cloned")
             if skill_ok else NO(f"{len(have)}/{len(used)} cloned — run scripts/fetch_quantskills.sh")))
    print()
    print(DIM("  enable with: python scripts/setup_real.py --enable "
              + " ".join(m for m, ok in
                         (("llm", llm_ok), ("data", data_ok), ("skill", skill_ok)) if ok) + " || (fill creds first)"))


def _probe(env: dict[str, str]) -> None:
    print("\nLive probes:")
    # LLM ping
    key = env.get("LLM_API_KEY")
    if key:
        try:
            import httpx
            base = env.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
            r = httpx.post(f"{base}/chat/completions",
                           headers={"Authorization": f"Bearer {key}"},
                           json={"model": env.get("LLM_MODEL", "deepseek-chat"),
                                 "messages": [{"role": "user", "content": "ping"}],
                                 "max_tokens": 1}, timeout=30)
            print("  LLM ping: " + (OK("200") if r.status_code == 200 else NO(f"{r.status_code} {r.text[:80]}")))
        except Exception as e:
            print("  LLM ping: " + NO(str(e)[:100]))
    else:
        print("  LLM ping: " + DIM("skipped (no key)"))
    # panda_data import + real login probe
    try:
        import panda_data  # noqa: F401
        print("  panda_data import: " + OK("installed"))
    except Exception:
        print("  panda_data import: " + NO("not installed (pip install panda_data==0.0.12)"))
        return
    user = env.get("DEFAULT_USERNAME")
    if user:
        try:
            base = env.get("JAVA_SERVICE_BASE_URL") or "http://pandadata.pandaaiquant.com"
            tok = panda_data.init_token(username=user, password=env.get("DEFAULT_PASSWORD", ""),
                                        base_url=base)
            print("  panda_data login: " + (OK("OK — account active, data ready")
                                            if tok else NO("no token returned")))
        except Exception as e:
            msg = str(e)[:120]
            hint = " → 账号需在 www.pandaaiquant.com/data-service 开通" if "未注册" in msg or "200006" in msg else ""
            print("  panda_data login: " + NO(msg + hint))
    else:
        print("  panda_data login: " + DIM("skipped (no DEFAULT_USERNAME)"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enable", nargs="*", choices=list(MODE_FLAG), default=[])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    for m in args.enable:
        key, val = MODE_FLAG[m]
        _set_flag(key, val)

    env = _read_env()
    _report(env)
    if args.check:
        _probe(env)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
