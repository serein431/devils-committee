#!/usr/bin/env python3
"""现场 demo 排练器 / 稳态兜底 —— 用真引擎驱动一场辩论，带旁白节奏打印到终端。

用途：
  1) 排练现场 3 分钟 demo 的节奏与台词（18/19 要求现场真机，不放概念视频）。
  2) 万一评审现场前端/网络翻车，这个纯终端流程是**同一个引擎**的稳态兜底。

跑法（在 devils-committee/ 下）：
  .venv/bin/python scripts/demo.py                      # 默认标的，真机跑
  .venv/bin/python scripts/demo.py 600519 --pace 0.6    # 指定标的 + 放慢节奏
  .venv/bin/python scripts/demo.py NVDA                 # 触发「过拟合→打回」剧情
  .venv/bin/python scripts/demo.py TSLA                 # 触发「全部通过」剧情（审计不是摆设）

它调 backend.orchestration，因此 LLM/DATA/SKILL 的 mock↔real 由 .env 决定，无需改这里。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.orchestration import DebateOrchestrator  # noqa: E402

# --- tiny ANSI helpers (degrade to plain if not a TTY) ---------------------
_TTY = sys.stdout.isatty()
def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _TTY else s
BOLD = lambda s: _c("1", s)
DIM = lambda s: _c("2", s)
GREEN = lambda s: _c("32", s)
RED = lambda s: _c("1;31", s)
CYAN = lambda s: _c("36", s)
YELLOW = lambda s: _c("33", s)

SIDE = {"bull": ("多头", "32"), "bear": ("空头", "31"),
        "macro": ("宏观", "35"), "risk": ("风控", "33")}


async def main(topic: str, pace: float) -> None:
    print()
    print(BOLD("┌─ 反方 · AI 投资辩论庭 ────────────────────────────────"))
    print(BOLD(f"│  开庭标的：{topic}"))
    print(BOLD("│  旁白：别人给你一个结论。我们让 AI 当面吵架、审计当场拆台。"))
    print(BOLD("└──────────────────────────────────────────────────────"))
    await asyncio.sleep(pace)

    orch = DebateOrchestrator()
    flagged = 0
    async for ev in orch.stream(topic, pace=pace):
        st = ev["stage"]
        if st == "argue":
            print("\n" + DIM("· 六个 Agent 就该标的并行取证 …"))
        elif st == "claim":
            name, color = SIDE.get(ev["side"], (ev["agent"], "36"))
            print(f"\n  {_c(color, '● ' + name)} {ev['text']}")
            skills = "、".join(ev.get("skills", []))
            if skills:
                print("    " + DIM("↳ 证据来自 " + skills))
        elif st == "audit":
            print("\n" + CYAN("· 审计 Agent 独立复核每一条论据 …"))
        elif st == "audit_flag":
            flagged += 1
            print("  " + RED(f"⚑ 标红 [{ev['claim_id']}·{ev['status']}] ") + ev["reason"])
            if ev.get("remediation"):
                print("    " + YELLOW("↳ 怎么补：") + ev["remediation"])
        elif st == "rebuttal":
            print("  " + YELLOW("↩ " + ev["msg"]))
        elif st == "synthesize":
            print("\n" + DIM("· 主持收敛共识与分歧 …"))
        elif st == "result":
            r = ev["result"]
            print("\n" + BOLD("── 分歧地图 ──"))
            for p in r["open_disagreements"]:
                tag = RED("仍在吵") if p["status"] == "open" else GREEN("已收敛")
                print(f"  【{p['topic']}】{tag}")
                print("    " + GREEN("正方 ") + p["bull_view"])
                print("    " + RED("反方 ") + p["bear_view"])
            print("\n" + BOLD("── 风险边界 ──"))
            for b in r["risk_boundaries"]:
                print("  • " + b)
            m = r["meta"]
            print("\n" + DIM(f"论点 {m['n_claims']} 条 · 审计标红 {m['n_flags']} 条 · "
                             f"用时 {r['elapsed_sec']}s · 模式 "
                             f"{m['modes']['llm_mode']}/{m['modes']['data_mode']}"))
            print(DIM("  " + r["disclaimer"]))

    print("\n" + BOLD("收尾一句："))
    print(BOLD("  “它没告诉你买不买。它让你") + GREEN("看懂了") + BOLD("买不买。"))
    print(BOLD("   这是我们两个 14 岁，想要的第一个理财老师。”"))
    if flagged == 0:
        print(DIM("\n（本标的审计全部放行——审计不是摆设，它真的会分辨。换 600519 看它标红。）"))
    print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("topic", nargs="?", default="帮我理解 600519 现在多空双方的理由和风险")
    ap.add_argument("--pace", type=float, default=0.7, help="每步停顿秒数（现场可调）")
    args = ap.parse_args()
    asyncio.run(main(args.topic, args.pace))
