# PandaAI（赛道 18）提交说明文档 · Devil's Committee

> 本文件由 `scripts/gen_submission.py` 从真实运行输出生成；示例与 Skills 清单均为实跑结果。
> `TODO` 处为需人工填写的对外信息（公网地址 / GitHub / 视频 / 团队联系方式）。

## 1. Agent 名称、简介、团队
- **名称**：反方 · The Devil's Committee — AI 投资辩论庭
- **简介**：多智能体对抗辩论 + 独立审计的理财认知教练。Bull/Bear/Macro/Risk 四个 Agent 并行取证，Audit Agent 独立复核每条论据（抓选择偏差/坏数据/过拟合）并可打回，Chair 收敛为「分歧地图 + 审计印章 + 风险边界」。**不给买卖建议，教用户自己判断**。仅供研究/教育。
- **团队**：Team ADVX2026（两名 14 岁自学者 + 两名大学生）。TODO：成员与联系方式。

## 2. Agent Card URL（A2A，公网可访问）
- `GET https://TODO-your-host/.well-known/agent-card.json`（服务运行时自动注入公网 `url`）
- 本地示例：`GET http://localhost:8080/.well-known/agent-card.json`
- 声明能力：`streaming: true`；广告技能：`debate_case`、`audit_claims`（两者均已实现）。

## 3. 服务地址 + 鉴权
- 服务：`POST https://TODO-your-host/a2a`（JSON；`?stream=1` 走 SSE）
- 健康检查：`GET /healthz`（评审期须常在线；见 `docs/service_checklist.md`）
- 鉴权：Bearer Token（设 `A2A_BEARER_TOKEN` 后必填）：`Authorization: Bearer <token>`
- 总响应 ≤ 20 分钟（全局预算 18 分钟 + 每 Agent 超时；SSE 先吐进度）。

## 4. 使用场景 / 架构 / Skills 调用方式 / 结果展示
**使用场景**：理财小白面对一个标的，网上信息一边倒只有结论。本 Agent 把正反方、风险、和「哪条论据被审计打回」摊开，教用户当裁判。

**架构（真协作，非串联）**：并行取证 → 独立审计（可打回）→ 收敛 → 合规过滤。详见 `README.md` 与 `docs/ARCHITECTURE.md`。

**Skills 调用方式**：每个角色调用对应 QuantSkills；`SKILL_MODE=cli` 时审计走真实 skill CLI，每条 verdict 带 `provenance`（mock / real-cli）可追溯。

**结果展示（真实运行摘录，标的 600519.SH）**：

```json
{
  "symbol": "600519.SH",
  "n_claims": 4,
  "audit_flags": [
    {
      "claim_id": "bear-1",
      "status": "bad_data",
      "severity": "medium",
      "provenance": "mock"
    },
    {
      "claim_id": "risk-1",
      "status": "bad_data",
      "severity": "medium",
      "provenance": "mock"
    }
  ],
  "open_disagreements": [
    {
      "topic": "因子信号站不站得住",
      "status": "consensus"
    },
    {
      "topic": "证据本身干不干净",
      "status": "open"
    },
    {
      "topic": "流动性与事件风险有多重",
      "status": "open"
    }
  ],
  "audit_engine": "mock",
  "disclaimer": "本内容由多智能体辩论生成，仅供学习与研究，不构成任何投资建议；不含买卖操作、目标价或收益承诺。历史/缓存数据不代表未来表现。"
}
```

## 5. 示例问题与预期输出（≥3）
- **输入**：`帮我理解一下 600519 贵州茅台 现在多空双方各自的理由和风险`
  - 预期：标的 `600519.SH`，4 条论点，审计 bear-1:bad_data、risk-1:bad_data；带风险提示。
- **输入**：`Explain the bull and bear case for NVDA and audit which arguments are overfit`
  - 预期：标的 `NVDA`，4 条论点，审计 bull-1:suspected_overfit；带风险提示。
- **输入**：`Walk me through the bull and bear case for TSLA and tell me which arguments survive audit`
  - 预期：标的 `TSLA`，4 条论点，审计 全部通过；带风险提示。

> 完整输入/预期输出见 `tests/examples/*.json`；`pytest` 回归保证不漂移。

## 6. 用到的数据 / 投研 Skills 列表（本场实跑）
- **数据**：panda_data（历史，仅研究）；本场窗口 `20240101..20241219`（mock，250 根）。
- **取证 Skills**：
  - `skill-corporate-action-adjustment-auditor` ← Risk
  - `skill-dalio-all-weather` ← Macro
  - `skill-factor-ranking-sage` ← Bull
  - `skill-holder-structure-scan` ← Bear
  - `skill-index-rebalance-event-study` ← Bear
  - `skill-portfolio-liquidity-stress-test` ← Bear、Risk
  - `skill-residual-guided-factor-selection` ← Bull
  - `skill-templeton-global-contrarian` ← Macro
  - `skill-us-sector-rotation` ← Bull
- **审计 Skills**：
  - `skill-corporate-action-adjustment-auditor` → 复核 bear-1、risk-1（provenance: mock）
- **全部**：`skill-corporate-action-adjustment-auditor`、`skill-dalio-all-weather`、`skill-factor-ranking-sage`、`skill-holder-structure-scan`、`skill-index-rebalance-event-study`、`skill-portfolio-liquidity-stress-test`、`skill-residual-guided-factor-selection`、`skill-templeton-global-contrarian`、`skill-us-sector-rotation`

## 7. GitHub / 联系方式 / 演示视频
- GitHub：`https://TODO-your-repo`（或邮件 `code@pandaai.online`）
- 演示视频（完整核心流程，现场真机非概念视频）：`https://TODO-video`；脚本见 `docs/demo_script.md`

## 8. 风险提示（合规）
> 本内容由多智能体辩论生成，仅供学习与研究，不构成任何投资建议；不含买卖操作、目标价或收益承诺。历史/缓存数据不代表未来表现。

- 全部对外输出经 `backend/compliance.py`：禁买卖/收益承诺/目标价/荐股，强制风险提示，审计标记保持可见。
- 数据仅用于比赛/研究，不构成投资建议；`SKILL_MODE=cli` 的 mock 数据明确标 `mock-synthetic`，不冒充真实数据。
