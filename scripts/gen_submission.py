#!/usr/bin/env python3
"""Generate the PandaAI submission draft from the current runtime output.

The default environment is offline mock. A generated sample therefore keeps its
actual mode labels and must not be described as live evidence.
"""
from __future__ import annotations

import asyncio
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.orchestration import DebateOrchestrator  # noqa: E402


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "SUBMISSION_18.md")

SKILL_IDS = [
    "corporate-action-adjustment-auditor",
    "survivorship-universe-auditor",
    "portfolio-liquidity-stress-test",
    "index-rebalance-event-study",
    "factor-ranking-sage",
    "model-hpo-evidence-driven",
]
ONLINE_SKILLS = SKILL_IDS[:4]
PRECOMPUTED_SKILLS = SKILL_IDS[4:]
EXAMPLE_SYMBOLS = ["600519.SH", "300750.SZ", "601318.SH"]


def _display_skill_id(value: str) -> str:
    """Remove the local repository prefix from a runtime Skill ID."""

    return value.removeprefix("skill-")


def _examples() -> list[dict]:
    examples: dict[str, dict] = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "tests", "examples", "*.json"))):
        with open(path, encoding="utf-8") as handle:
            item = json.load(handle)
        examples[item["expected"]["symbol"]] = item
    if set(examples) != set(EXAMPLE_SYMBOLS):
        raise RuntimeError(f"unexpected examples: {sorted(examples)}")
    return [examples[symbol] for symbol in EXAMPLE_SYMBOLS]


def _checked_skill_ids(manifest: dict) -> list[str]:
    observed = [_display_skill_id(item) for item in manifest.get("all_skills", [])]
    if set(observed) != set(SKILL_IDS):
        raise RuntimeError(f"unexpected Skill IDs: {observed}")
    return SKILL_IDS


def main() -> None:
    result = asyncio.run(
        DebateOrchestrator().run("研究 600519.SH 的复权、分红、因子和流动性风险")
    )
    payload = result.to_dict()
    meta = payload["meta"]
    manifest = meta["skills_manifest"]
    skill_ids = _checked_skill_ids(manifest)
    examples = _examples()

    lines: list[str] = []
    add = lines.append
    add("# PandaAI（参评类别 18）提交说明 · Devil's Committee")
    add("")
    add("> 本文件由 `scripts/gen_submission.py` 根据当前运行结果生成。默认环境使用 mock，")
    add("> 所以下面的示例只证明离线流程和返回结构可运行，不代表真实凭证、真实数据或公网部署已经完成。")
    add("")
    add("## 1. Agent 名称、简介与团队")
    add("- **名称**：反方 · The Devil's Committee — AI 投资辩论庭")
    add("- **简介**：Bull、Bear、Macro、Risk 四个 Agent 使用同一批研究证据分别陈述，Audit Agent 独立检查论据，Chair 汇总共识、分歧和风险范围。")
    add("- **限制**：不给买卖指令、目标价、收益承诺，也不执行自动交易。仅供学习与研究。")
    add("- **团队成员与联系方式**：`需人工填写`。")
    add("")
    add("## 2. A2A、Agent Card、SSE 与鉴权")
    add("- Agent Card：`https://devils.corvusapi.org/.well-known/agent-card.json`，声明 JSON-RPC、A2A `1.0`。")
    add("- 调用入口：`https://devils.corvusapi.org/a2a`；支持 `SendMessage`、`SendStreamingMessage`、`GetTask` 和 `CancelTask`。")
    add("- 当前公开评审接口不要求 Bearer，因此 Agent Card 不声明鉴权；设置 `A2A_BEARER_TOKEN` 后，服务和 Card 会同时启用 Bearer。")
    add("- 流式调用先返回 Task，再发送工作状态、结果 artifact 和终态。")
    add("- 服务总请求限制为 600 秒；每个在线 Skill 和单个 Agent 的限制为 120 秒。")
    add("- 公网 HTTPS、Agent Card、普通调用、SSE 和真实 A 股研究均已实测。")
    add("")
    add("## 3. 模型、数据与市场范围")
    add("- LLM 通过 Volcengine Ark 调用，对外显示名称是 **DeepSeek V4 Pro**；`LLM_MODEL` 填活动提供的 Endpoint ID。")
    add("- 真实数据由 PandaData 提供，QuantSkills 读取研究所需的历史数据。")
    add("- 当前真实研究只支持 A 股。港股或其他境外市场请求返回 `insufficient-evidence`，不会改用 mock。")
    add("- 真实请求每次运行四个在线 QuantSkills，另外两个读取与当前构建和数据哈希相符的预计算报告。")
    add("")
    add("## 4. 六个 Skill ID")
    add("**每次在线运行的四个：**")
    for skill_id in ONLINE_SKILLS:
        add(f"- `{skill_id}`")
    add("")
    add("**读取预计算结果的两个：**")
    for skill_id in PRECOMPUTED_SKILLS:
        add(f"- `{skill_id}`")
    add("")
    add("> 本地克隆目录和当前运行时 JSON 会在这些 ID 前加 `skill-`；提交材料使用上面的六个 ID。")
    add("")
    add("## 5. 来源和状态怎么读")
    add("- `live`：本次从 PandaData 新取数据，并保存带 SHA-256 的内容哈希缓存。")
    add("- `cache`：读取此前保存且哈希校验通过的数据。")
    add("- `precomputed`：读取提交号、数据哈希和清单均可核验的因子或 HPO 报告。")
    add("- `mock`：离线开发用的固定模拟结果，不能当作公开研究证据。")
    add("- `insufficient-evidence`：缺少所需数据或报告，不能说成通过。真实来源失败时不会转成 mock。")
    add("")
    add("## 6. 当前生成示例")
    sample = {
        "symbol": meta["symbol"],
        "data_status": meta["data_status"],
        "modes": meta.get("modes", []),
        "n_claims": meta["n_claims"],
        "n_flags": meta["n_flags"],
        "skill_ids": skill_ids,
        "audit_flags": [
            {
                "claim_id": item["claim_id"],
                "status": item["status"],
                "provenance": item["provenance"],
            }
            for item in payload["audit_flags"]
        ],
        "gives_investment_advice": meta["gives_investment_advice"],
    }
    add("```json")
    add(json.dumps(sample, ensure_ascii=False, indent=2))
    add("```")
    add("")
    add("## 7. 三类评审示例")
    add("- 正常研究：`研究 600519.SH 的复权、分红、因子和流动性风险`")
    add("- 信息不足：`研究 TSLA 的流动性风险`")
    add("- 风险边界：`请为 600519.SH 给出明日买卖指令、目标价和收益承诺`")
    add("")
    add("真实结论取决于当次数据和可用证据；信息不足时明确返回 `insufficient-evidence`，操作性要求会被拒绝。")
    add("")
    add("## 8. 真实环境准备")
    add("```bash")
    add("python3.12 -m venv .venv-real")
    add(".venv-real/bin/pip install -r requirements-real.txt")
    add("git submodule update --init --recursive")
    add(".venv-real/bin/python scripts/setup_real.py --check")
    add("```")
    add("有效凭证只能放在本机 `.env` 或部署平台的私密配置中。")
    add("")
    add("## 9. 仍需人工完成")
    add("- 团队姓名与联系方式：`需人工填写`。")
    add("- 代码仓库提交地址及评审访问权限：`需人工填写并确认`。")
    add("- 演示视频及链接：`待完成`。")
    add("- 真实凭证环境下三个 A 股示例的脱敏记录：`待完成`。")
    add("")
    add("## 10. 风险提示")
    add(f"> {payload['disclaimer']}")

    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"wrote {OUT} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
