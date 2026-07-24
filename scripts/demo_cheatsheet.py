#!/usr/bin/env python3
"""Generate a demo sheet for the three published A-share research examples.

Run it in the same DATA_MODE/SKILL_MODE used for the presentation. The sheet
records observed data status and audit outcomes; it does not promise that a
symbol will always produce a particular verdict.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import CONFIG  # noqa: E402
from backend.orchestration import DebateOrchestrator  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "demo_cheatsheet.md")

EXAMPLES = {
    "600519.SH": "贵州茅台：复权、分红、因子和流动性风险",
    "300750.SZ": "宁德时代：成长因子、波动、流动性和指数事件",
    "601318.SH": "中国平安：分红、股票池和风险证据",
}


def main() -> None:
    rows = []
    for symbol, question in EXAMPLES.items():
        result = asyncio.run(
            DebateOrchestrator().run(f"研究 {symbol} 的{question.split('：', 1)[1]}")
        )
        statuses = sorted({item.status for item in result.verdicts})
        outcome = "、".join(statuses) if statuses else "没有可审计论据"
        rows.append(
            (
                symbol,
                question.split("：", 1)[0],
                result.meta["data_status"],
                result.meta["n_claims"],
                result.meta["n_flags"],
                outcome,
                "/".join(result.meta.get("modes", [])) or "unknown",
            )
        )

    mode = CONFIG.summary()
    lines = [
        "# 现场 Demo · 三个 A 股研究示例",
        "",
        f"> 生成设置：模型 `{mode['llm_mode']}` · 数据 `{mode['data_mode']}` · 技能 `{mode['skill_mode']}`。",
        "> 审计结论来自本次运行。数据、缓存或模型变化后，结论可能不同，演示前请重跑。",
        "",
        "| 标的 | 名称 | 数据状态 | 论据数 | 标记数 | 本次审计状态 | 证据模式 |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for row in rows:
        symbol, name, data_status, claims, flags, outcome, modes = row
        lines.append(
            f"| `{symbol}` | {name} | {data_status} | {claims} | {flags} | {outcome} | {modes} |"
        )
    lines += [
        "",
        "## 现场说明",
        "",
        "- 先说明当前数据状态和证据模式，再讲审计结果。",
        "- 没有被标记不等于标的一定可靠，只表示本次证据中没有发现可证实的问题。",
        "- 没有论据时，应说明授权数据不足或研究失败，不要说成审计通过。",
        "- 页面和终端都不给买卖建议，只展示证据、分歧和风险范围。",
    ]

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {OUT} ({len(rows)} examples, mode={mode['data_mode']})")


if __name__ == "__main__":
    main()
