#!/usr/bin/env python3
"""Generate a live-demo cheat sheet: which common ticker triggers which audit
outcome, so the presenter KNOWS in advance what any judge-supplied ticker will do
(turns 'hope it works' into 'I know exactly what it does').

    .venv/bin/python scripts/demo_cheatsheet.py            # -> docs/demo_cheatsheet.md

IMPORTANT: outcomes depend on the current mode. Re-run in the SAME mode you will
demo in (mock offline vs DATA_MODE=panda real) — the printed header records it.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.config import CONFIG                          # noqa: E402
from backend.orchestration import DebateOrchestrator       # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "demo_cheatsheet.md")

TICKERS = {
    "600519": "贵州茅台", "000858": "五粮液", "601318": "中国平安",
    "000001": "平安银行", "600036": "招商银行", "300750": "宁德时代",
    "002594": "比亚迪", "688981": "中芯国际", "000002": "万科A",
    "601899": "紫金矿业", "600030": "中信证券", "000651": "格力电器",
    "AAPL": "Apple", "TSLA": "Tesla", "NVDA": "Nvidia", "MSFT": "Microsoft",
    "GOOG": "Google", "META": "Meta", "AMZN": "Amazon",
}


def main() -> None:
    rows = []
    for s, name in TICKERS.items():
        r = asyncio.run(DebateOrchestrator().run(f"{s} 多空"))
        flags = r.audit_flags()
        outcome = "全部通过" if not flags else "、".join(sorted(set(
            f"{v.claim_id.split('-')[0]}:{v.status}" for v in flags)))
        rows.append((s, name, r.meta["n_flags"], outcome, r.meta["audit_engine"]))

    m = CONFIG.summary()
    L = ["# 现场 Demo · 标的应对速查表", "",
         f"> 生成模式：模型 `{m['llm_mode']}` · 数据 `{m['data_mode']}` · 审计 `{m['skill_mode']}`。",
         "> ⚠️ 换模式（尤其 `DATA_MODE=panda` 真数据）结论会变——**用你现场要用的模式重跑本表**。", ""]
    L += ["| 标的 | 名称 | 标红数 | 审计结论 |", "|---|---|---|---|"]
    for s, name, n, o, _ in rows:
        L.append(f"| `{s}` | {name} | {n} | {o} |")
    L += ["", "## 主持人应对（按结论类型）", "",
          "- **全部通过**（如五粮液/宁德/茅台外的多数）→ “这只票它挑不出毛病，就放行——"
          "证明审计是真的在分辨，不是逢多必红。这本身就是可信度。”",
          "- **bull:selection_bias** → “看，多头的因子被审计当场标红：小样本高 IC，像只挑赢家来吹。”",
          "- **bull:suspected_overfit** → “多头这条被判过拟合——像背答案考试，换套题就不灵，还被打回重证。”",
          "- **bear/risk:bad_data** → “空头/风控引用的价格序列被查出未复权跳空——证据本身带病，先修数据。”",
          "- **多条混合**（如中国平安/万科/Meta）→ 最有戏：多空两边都被挑出不同毛病，分歧地图最丰富。",
          "",
          "## 稳妥选择",
          "- 想**必现标红**演高光：中国平安 `601318`、平安银行 `000001`、万科 `000002`、Meta（三条混合）。",
          "- 想演**审计会放行**（证明不唬人）：宁德 `300750`、五粮液 `000858`、中信证券 `600030`、Tesla。",
          "- 评委给的票不在表内也不慌——同样的引擎当场跑，结论可解释、带溯源。"]

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"wrote {OUT} ({len(rows)} tickers, mode={m['data_mode']})")


if __name__ == "__main__":
    main()
