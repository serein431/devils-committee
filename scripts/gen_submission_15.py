#!/usr/bin/env python3
"""Generate the AI financial-literacy coach submission draft."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import compliance  # noqa: E402
from backend.orchestration import DebateOrchestrator  # noqa: E402
from backend.plain import PLAIN_AUDIT  # noqa: E402


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "SUBMISSION_15.md")

SKILL_IDS = [
    "corporate-action-adjustment-auditor",
    "survivorship-universe-auditor",
    "portfolio-liquidity-stress-test",
    "index-rebalance-event-study",
    "factor-ranking-sage",
    "model-hpo-evidence-driven",
]
EXAMPLE_SYMBOLS = ["600519.SH", "300750.SZ", "601318.SH"]


def main() -> None:
    audit = asyncio.run(
        DebateOrchestrator().audit_claims(
            "研究 600519.SH 的复权、分红、因子和流动性风险"
        )
    )
    lines: list[str] = []
    add = lines.append

    add("# 度小满（参评类别 15）提交说明 · AI 理财认知教练")
    add("")
    add("> 方向：引导用户理解证据，不给操作答案。当前生成示例会保留实际来源标签；默认 mock 只用于本地开发。")
    add("")
    add("## 1. 目标用户")
    add("面向想理解股票研究材料、但不熟悉量化术语的初学者。产品把多头、空头、宏观和风险理由分开呈现，再说明哪些证据缺失或受到审计质疑。")
    add("")
    add("## 2. 引导方式和限制")
    add("用户输入一个 A 股问题后，四个 Agent 分别阅读同一批证据，Audit Agent 检查选择偏差、数据问题和过拟合，Chair 只汇总共识、分歧和风险范围。")
    add("产品不给买卖指令、目标价、收益承诺，也不执行自动交易。所有公开文本经过 `backend/compliance.py` 检查。")
    add("")
    add("常见审计状态的人话说明：")
    for status, explanation in PLAIN_AUDIT.items():
        add(f"- `{status}`：{explanation}")
    add("")
    add("## 3. 技术资源")
    add("- 模型：Volcengine Ark 上显示为 **DeepSeek V4 Pro**；`LLM_MODEL` 填活动 Endpoint ID。")
    add("- 数据：PandaData 历史数据；当前真实研究只支持 A 股，其他市场返回 `insufficient-evidence`。")
    add("- Skills：真实请求每次运行四个在线 QuantSkills，并读取两个预计算结果。每个在线 Skill 与单个 Agent 限制 120 秒，整个请求限制 600 秒。")
    add("- 接口：A2A、SSE、Bearer 鉴权和 Agent Card 与参评类别 18 共用同一后端。")
    add("")
    add("六个 Skill ID：")
    for index, skill_id in enumerate(SKILL_IDS):
        kind = "在线" if index < 4 else "预计算"
        add(f"- `{skill_id}`（{kind}）")
    add("")
    add("## 4. 来源和失败处理")
    add("- `live` 是本次新取的数据，`cache` 是内容哈希校验通过的本地数据。")
    add("- `precomputed` 是与当前提交号和数据哈希相符的因子或 HPO 报告。")
    add("- `mock` 只服务于离线开发，不能用于证明真实研究已经完成。")
    add("- 缺失证据标为 `insufficient-evidence`。真实数据、模型或 Skill 失败时不会改成 mock。")
    add("")
    add("## 5. 当前本地生成示例")
    add(f"- 标的：`{audit['symbol']}`")
    add(f"- 数据状态：`{audit['data_status']}`")
    add(f"- 来源：`{'/'.join(audit.get('modes', [])) or 'none'}`")
    add(f"- 论据数：`{audit['n_claims']}`；审计标记数：`{audit['n_flags']}`")
    for item in audit["audits"]:
        add(f"- {item['agent']}：`{item['status']}`，来源 `{item['provenance']}`")
    add("")
    add(f"> {audit['disclaimer']}")
    add("")
    add("## 6. 三个演示标的")
    add("、".join(f"`{symbol}`" for symbol in EXAMPLE_SYMBOLS) + "。演示前按实际运行模式重跑，不预先承诺审计结论。")
    add("")
    add("## 7. 本地与真实环境")
    add("默认开发可用 mock。真实环境要求 Python 3.12 和 `requirements-real.txt`：")
    add("```bash")
    add("python3.12 -m venv .venv-real")
    add(".venv-real/bin/pip install -r requirements-real.txt")
    add("./scripts/fetch_quantskills.sh")
    add(".venv-real/bin/python scripts/setup_real.py --check")
    add("```")
    add("")
    add("## 8. 完成情况与人工事项")
    add("- 本地离线服务、A2A、SSE 和教练页面可由仓库代码运行。")
    add(f"- 合规检查目前包含 {len(compliance.BANNED_PATTERNS)} 类规则。")
    add("- 团队姓名与分工：`需人工填写`。")
    add("- 真实用户试用人数、原话和改动记录：`待完成`。")
    add("- 公网访问地址：`待完成`。")
    add("- 演示视频及链接：`待完成`。")

    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"wrote {OUT} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
