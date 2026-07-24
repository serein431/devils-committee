# 系统架构 · AI 投资辩论庭

同一后端提供教练页面和 A2A 调用。默认开发使用 mock；真实环境使用 Volcengine Ark、PandaData、四个在线 QuantSkills 和两个预计算报告。

## 请求路径

```text
调用方
  ├─ GET /.well-known/agent-card.json
  ├─ GET /healthz
  └─ POST /a2a ── Bearer 鉴权可选 ── JSON 或 SSE
         │
         ▼
  ResearchRequest：解析 A 股代码和研究参数
         │  不支持的市场 → insufficient-evidence
         ▼
  PandaData 数据包
         ├─ live：本次新取数据
         └─ cache：内容哈希核验通过的本地数据
         │
         ├─ 四个在线 QuantSkills（每个最多 120 秒）
         └─ 两个 precomputed 报告
         │
         ▼
  Bull / Bear / Macro / Risk 并行陈述（单个 Agent 最多 120 秒）
         ▼
  Audit Agent 独立检查每条论据
         ▼
  Chair 汇总共识、分歧和风险范围
         ▼
  compliance.py 移除操作性表述并附风险提示
         ▼
  A2A JSON / SSE / 教练页面
```

整个请求限制为 600 秒。SSE 只负责发送阶段事件，不会放宽时间限制。

## 六个 Skill

真实请求每次在线运行：

1. `corporate-action-adjustment-auditor`
2. `survivorship-universe-auditor`
3. `portfolio-liquidity-stress-test`
4. `index-rebalance-event-study`

读取预计算结果：

5. `factor-ranking-sage`
6. `model-hpo-evidence-driven`

本地仓库目录和当前运行时 JSON 使用 `skill-` 前缀。上面的名称是提交材料使用的六个 ID。

## 数据与缓存

真实研究当前只支持 A 股。固定演示标的是 `600519.SH`、`300750.SZ` 和 `601318.SH`。港股或其他境外市场不会进入真实研究流程，而是返回 `insufficient-evidence`。

PandaData 缓存键包含方法、参数、SDK 版本和数据版本。保存 Parquet 后计算 SHA-256；读取时会再次核验文件哈希。预计算报告还要检查提交号、数据哈希、来源文件哈希和标的范围。

## 来源和状态

| 值 | 含义 |
|---|---|
| `live` | 本次从 PandaData 新取的数据或基于该数据在线运行的 Skill |
| `cache` | 经内容哈希核验的本地数据或基于该数据在线运行的 Skill |
| `precomputed` | 与当前构建和来源文件相符的因子或 HPO 报告 |
| `mock` | 离线开发用的固定模拟结果，不能当作真实证据 |
| `insufficient-evidence` | 缺少必要字段、记录或报告，不能说成通过 |

真实数据、模型或 Skill 失败时不会改用 mock。公开响应通过 `meta.modes`、`skills_manifest`、`status` 和 `dataset_hashes` 保留来源说明。

## 模型与接口

LLM 使用 Volcengine Ark 的 OpenAI 兼容接口。显示名称是 **DeepSeek V4 Pro**，`LLM_MODEL` 填活动提供的 Endpoint ID。A2A 服务公开 Agent Card，支持 SSE；设置 `A2A_BEARER_TOKEN` 后必须使用 Bearer 鉴权。

## 合规限制

系统只解释证据和风险，不给买卖指令、目标价、收益承诺，也不执行自动交易。所有公开文本经过 `backend/compliance.py`，缺失证据必须保持可见。
