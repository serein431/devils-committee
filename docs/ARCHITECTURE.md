# 系统架构 · AI 投资辩论庭

> 目标：后端满足 18 PandaAI（A2A Remote Agent、真协作、审计新形态），前端满足 15 度小满（理财教练、不给答案、合规边界）。同一引擎，两张脸。

## 数据流

```
用户/评委提问（自然语言，一个标的或一笔配置）
        │
        ▼
┌─────────────────────────────────────────────┐
│  A2A Server  (/.well-known/agent-card.json)   │  ← 18 联调入口；FastAPI + SSE streaming
│  skills: debate_case, audit_claims            │
└───────────────┬───────────────────────────────┘
                │  DebateOrchestrator.run(topic)
   ┌────────────┼───────────────────────────────┐
   ▼            ▼            ▼           ▼
 Bull        Bear         Macro       Risk        ← 并行取证（asyncio.gather）
   │            │            │           │           每个 Agent 调 QuantSkills / panda_data
   └────────────┴─────┬──────┴───────────┘
                      ▼
              Audit Agent（独立复核）              ← survivorship-bias/data-quality/hpo-evidence 审计
              对每条论据打： pass / overfit? / thin_data
                      ▼
              Chair Agent（收敛）                  ← 研报生成 skill
              → 共识 / 未解分歧 / 风险提示
                      ▼
        ┌─────────────┴─────────────┐
        ▼                           ▼
  A2A 结构化响应(18)          教练前端渲染(15)
  （JSON：debate + audit）    （分歧地图 + 审计印章 + 边界）
```

## 组件与赛道映射

| 组件 | 满足赛道 | 说明 |
|---|---|---|
| `a2a_server.py` | 18 | Agent Card + A2A 协议 + 稳定在线 + ≤20min |
| `agents.py` / `orchestration.py` | 18 | 对抗辩论 + 独立审计 = 真协作 |
| `skills/` 封装 | 18 | QuantSkills（Verified）+ panda_data |
| `web/`（前端） | 15 | 教练 UX、分歧地图、审计印章、合规边界 |
| 全程 Qoder 开发 + 录屏 | 04 | 多智能体协作开发证据 |
| `docs/build-in-public/` | 07 | 小红书笔记素材归档 |

## 关键非功能约束（来自 18 硬要求）
- **稳定在线**：评审期服务不可掉线 → 部署带健康检查 + 自动重启（见 `service_checklist.md`）。
- **总响应 ≤ 20 分钟**：辩论要设 per-agent 超时 + 全局预算；用 streaming 先吐进度，避免评委等待感。
- **可解释**：每条结论回链到具体 skill 调用与数据，审计结果显式呈现。
- **合规**：输出统一经 `compliance.py` 过滤——禁"买/卖/收益承诺/荐股"，强制附风险提示。

## 数据窗口策略（7 天权限）
- 开通后立即用 `panda_data` 拉取 demo 标的所需历史数据，落 DuckDB/Parquet 本地缓存（QuantSkills 自带 data warehouse 能力）。
- 联调与终审都走缓存，避免窗口过期或限流影响现场。

## 待群内确认（TODO(feishu)）
- panda_data 的确切安装/鉴权/调用签名
- QuantSkills 各 skill 仓库的调用入口
- A2A 示例 Agent Card 字段 + 测试环境 URL
- DeepSeek API base_url / key / 额度
