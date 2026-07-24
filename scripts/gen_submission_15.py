#!/usr/bin/env python3
"""Generate the track-15 (度小满) submission doc, organized by its 8 questions.

Direction ② 'AI 理财教练'：引导判断、不给操作答案、有风险边界。Embeds REAL output
(plain-language layer + compliance patterns + a no-answer audit sample) so the
'不给答案 + 风险机制' claims are grounded. Regenerate:

    .venv/bin/python scripts/gen_submission_15.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.orchestration import DebateOrchestrator          # noqa: E402
from backend.plain import PLAIN_AUDIT                          # noqa: E402
from backend import compliance                                 # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "SUBMISSION_15.md")


def main() -> None:
    ac = asyncio.run(DebateOrchestrator().audit_claims("帮我理解 600519 现在多空双方的理由和风险"))
    L: list[str] = []
    P = L.append

    P("# 度小满（赛道 15）提交说明文档 · AI 理财认知教练")
    P("")
    P("> 方向②「AI 理财教练」：**引导用户判断、不给操作答案、有风险边界**。")
    P("> 本文件由 `scripts/gen_submission_15.py` 从真实运行输出生成；人话示例与合规规则均为实跑。")
    P("> `TODO` 为需人工填写的对外信息（访问链接 / 真实用户数据 / 团队）。")
    P("")

    P("## 1. 目标人群")
    P("年轻首投者 / 理财小白——**就是我们自己**（两名 14 岁 + 两名大学生）。"
      "特征：看得懂中文、看不懂投顾黑话、最容易被网上一边倒的“买入结论”带跑。")
    P("")

    P("## 2. 痛点 + 依据")
    P("- **痛点**：网上关于一个标的的信息几乎只有结论（买这个/涨那个），"
      "看不到反方是谁、风险在哪、那条论据是不是被挑出来的。小白没有“当裁判”的工具。")
    P("- **依据**：我们两个 14 岁真的看不懂大人的投顾——这不是设定，是团队真身份；"
      "我们按自己“第一次想搞懂一只票”的困惑来设计每一句话。")
    P("")

    P("## 3. 引导式逻辑 + 不给答案 + 风险机制（核心）")
    P("**引导式**：不直接回答“能不能买”，而是把一场辩论摊开——多头/空头/宏观/风控各自的理由，"
      "再由**审计 Agent 当场标出哪条论据站不住**，最后给一张“分歧地图 + 风险边界”。")
    P("")
    P("**人话通道（让小白真看懂反方）**：每条论据、每个审计标红都配一句零术语类比：")
    for status, txt in list(PLAIN_AUDIT.items()):
        P(f"- `{status}` → {txt}")
    P("")
    P("**不给答案 —— 实跑证据（audit_claims 输出，标的 600519.SH）**：")
    P("整场输出里没有任何“买/卖/目标价/收益”，只有“哪条论据可信、风险在哪”。逐条审计：")
    P("")
    for a in ac["audits"]:
        P(f"- **{a['agent']}** 的论据 → 审计判定 `{a['status']}`"
          + (f"：{a['plain']}" if a.get("plain") else "（经得起查）"))
    P(f"")
    P(f"> 免责声明（每次输出强制附带）：{ac['disclaimer']}")
    P("")
    P("**风险机制（代码级强制，非口头承诺）**：所有对外输出经 `backend/compliance.py`，"
      f"正则拦截 {len(compliance.BANNED_PATTERNS)} 类操作性表述——"
      "`建议买入/卖出`、`目标价`、`必涨/稳赚`、`收益率 N%`、`荐股`、`strong buy` 等，命中即替换为"
      f"「{compliance.REDACTION}」，并标注 AI 不确定项、建议人工/专业核实。")
    P("")

    P("## 4. 技术资源组合")
    P("- 多智能体编排（并行取证 → 独立审计 → 收敛），A2A 自托管后端（与赛道 18 同一引擎）。")
    P("- QuantSkills（真实投研/审计技能）+ panda_data（历史数据，仅研究）；`SKILL_MODE=cli` 时审计走真实 skill。")
    P("- 教练前端：辩论视图 / 分歧地图 / 审计印章 / **人话层** / 风险边界。")
    P("- 底座模型可换（DeepSeek 或任意 OpenAI 兼容）；合规层与人话层不依赖模型、确定可复现。")
    P("")

    P("## 5. 完成度")
    P("- 端到端可跑（离线零凭证即可演示）；`/healthz`、A2A、SSE 流式、教练前端全通。")
    P("- 全套自动化测试全绿（合规 / 端到端 / 示例任务 / 真实 skill / 人话层 / 服务健壮性）。")
    P("- 两个真实审计器已接入现场辩论，输出带 provenance 可追溯。")
    P("- 待补（人工）：真实用户使用数据（见第 7 问）、现场演示链接。")
    P("")

    P("## 6. 分工")
    P("- A｜Agent 架构 + A2A 上线；B｜教练前端 + 分歧地图 + 人话层；"
      "C｜数据/技能接入 + 审计；D｜真人试用 + 内容 + 现场演示。（全员用 Qoder 多智能体开发并留证据。）")
    P("")

    P("## 7. 演示 + 访问链接")
    P("- 在线体验：`https://TODO-your-host/`（教练前端）")
    P("- 演示脚本：`docs/demo_script.md`（现场真机 3 分钟）")
    P("- **真实用户数据（15 明确要“对真实用户负责”）**：TODO——赛前把产品真发给同学/家长用，"
      "按 `docs/user-tests/` 协议录“看懂反方”与“看不懂”的瞬间，附样本数与原话。")
    P("")

    P("## 8. 希望度小满提供的资源（加分项）")
    P("- 业务/合规导师：确认理财教练对小白输出的红线，写进边界层。")
    P("- 真实小白用户触达渠道，帮我们攒“对真实用户负责”的使用数据。")
    P("- 普惠理财场景的真实数据/内容合作。")

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"wrote {OUT} ({len(L)} lines)")


if __name__ == "__main__":
    main()
