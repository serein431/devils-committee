#!/usr/bin/env python3
"""Generate the track-18 submission doc (docs/SUBMISSION_18.md) from live output.

Assembles the official PandaAI submission checklist into one judge-facing Markdown,
auto-embedding a REAL example output + the actual QuantSkills manifest so '结果展示'
and '用到的 Skills 列表' are grounded, not hand-waved. Regenerate anytime:

    .venv/bin/python scripts/gen_submission.py
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


def _examples() -> list[dict]:
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "tests", "examples", "*.json"))):
        out.append(json.load(open(p, encoding="utf-8")))
    return out


def main() -> None:
    demo = asyncio.run(DebateOrchestrator().run("帮我理解 600519 现在多空双方的理由和风险"))
    d = demo.to_dict()
    man = d["meta"]["skills_manifest"]
    exs = _examples()

    lines: list[str] = []
    P = lines.append
    P("# PandaAI（赛道 18）提交说明文档 · Devil's Committee")
    P("")
    P("> 本文件由 `scripts/gen_submission.py` 从真实运行输出生成；示例与 Skills 清单均为实跑结果。")
    P("> `TODO` 处为需人工填写的对外信息（公网地址 / GitHub / 视频 / 团队联系方式）。")
    P("")

    P("## 1. Agent 名称、简介、团队")
    P("- **名称**：反方 · The Devil's Committee — AI 投资辩论庭")
    P("- **简介**：多智能体对抗辩论 + 独立审计的理财认知教练。Bull/Bear/Macro/Risk 四个 Agent "
      "并行取证，Audit Agent 独立复核每条论据（抓选择偏差/坏数据/过拟合）并可打回，Chair 收敛为"
      "「分歧地图 + 审计印章 + 风险边界」。**不给买卖建议，教用户自己判断**。仅供研究/教育。")
    P("- **团队**：Team ADVX2026（两名 14 岁自学者 + 两名大学生）。TODO：成员与联系方式。")
    P("")

    P("## 2. Agent Card URL（A2A，公网可访问）")
    P("- `GET https://TODO-your-host/.well-known/agent-card.json`（服务运行时自动注入公网 `url`）")
    P("- 本地示例：`GET http://localhost:8080/.well-known/agent-card.json`")
    P("- 声明能力：`streaming: true`；广告技能：`debate_case`、`audit_claims`（两者均已实现）。")
    P("")

    P("## 3. 服务地址 + 鉴权")
    P("- 服务：`POST https://TODO-your-host/a2a`（JSON；`?stream=1` 走 SSE）")
    P("- 健康检查：`GET /healthz`（评审期须常在线；见 `docs/service_checklist.md`）")
    P("- 鉴权：Bearer Token（设 `A2A_BEARER_TOKEN` 后必填）：`Authorization: Bearer <token>`")
    P("- 总响应 ≤ 20 分钟（全局预算 18 分钟 + 每 Agent 超时；SSE 先吐进度）。")
    P("")

    P("## 4. 使用场景 / 架构 / Skills 调用方式 / 结果展示")
    P("**使用场景**：理财小白面对一个标的，网上信息一边倒只有结论。本 Agent 把正反方、风险、"
      "和「哪条论据被审计打回」摊开，教用户当裁判。")
    P("")
    P("**架构（真协作，非串联）**：并行取证 → 独立审计（可打回）→ 收敛 → 合规过滤。详见 `README.md` 与 `docs/ARCHITECTURE.md`。")
    P("")
    P("**Skills 调用方式**：每个角色调用对应 QuantSkills；`SKILL_MODE=cli` 时审计走真实 skill CLI，"
      "每条 verdict 带 `provenance`（mock / real-cli）可追溯。")
    P("")
    P("**结果展示（真实运行摘录，标的 600519.SH）**：")
    P("")
    P("```json")
    sample = {
        "symbol": d["meta"]["symbol"],
        "n_claims": d["meta"]["n_claims"],
        "audit_flags": [{"claim_id": v["claim_id"], "status": v["status"],
                         "severity": v["severity"], "provenance": v["provenance"]}
                        for v in d["audit_flags"]],
        "open_disagreements": [{"topic": p["topic"], "status": p["status"]}
                               for p in d["open_disagreements"]],
        "audit_engine": d["meta"]["audit_engine"],
        "disclaimer": d["disclaimer"],
    }
    P(json.dumps(sample, ensure_ascii=False, indent=2))
    P("```")
    P("")

    P("## 5. 示例问题与预期输出（≥3）")
    for ex in exs:
        e = ex["expected"]
        flags = "、".join(f"{f['claim_id']}:{f['status']}" for f in e["audit_flags"]) or "全部通过"
        P(f"- **输入**：`{ex['input']['topic']}`")
        P(f"  - 预期：标的 `{e['symbol']}`，{e['n_claims']} 条论点，审计 {flags}；带风险提示。")
    P("")
    P("> 完整输入/预期输出见 `tests/examples/*.json`；`pytest` 回归保证不漂移。")
    P("")

    P("## 6. 用到的数据 / 投研 Skills 列表（本场实跑）")
    P(f"- **数据**：panda_data（历史，仅研究）；本场窗口 `{man['data']['window']}`"
      f"（{man['data']['source']}，{man['data']['n_bars']} 根）。")
    P("- **取证 Skills**：")
    for e in man["evidence_skills"]:
        P(f"  - `{e['skill']}` ← {'、'.join(e['used_by'])}")
    P("- **审计 Skills**：")
    for a in man["audit_skills"]:
        P(f"  - `{a['skill']}` → 复核 {'、'.join(a['verdict_for'])}（provenance: {'/'.join(a['provenance'])}）")
    P(f"- **全部**：{'、'.join('`'+s+'`' for s in man['all_skills'])}")
    P("")

    P("## 7. GitHub / 联系方式 / 演示视频")
    P("- GitHub：`https://TODO-your-repo`（或邮件 `code@pandaai.online`）")
    P("- 演示视频（完整核心流程，现场真机非概念视频）：`https://TODO-video`；脚本见 `docs/demo_script.md`")
    P("")

    P("## 8. 风险提示（合规）")
    P(f"> {d['disclaimer']}")
    P("")
    P("- 全部对外输出经 `backend/compliance.py`：禁买卖/收益承诺/目标价/荐股，强制风险提示，审计标记保持可见。")
    P("- 数据仅用于比赛/研究，不构成投资建议；`SKILL_MODE=cli` 的 mock 数据明确标 `mock-synthetic`，不冒充真实数据。")

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {OUT} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
