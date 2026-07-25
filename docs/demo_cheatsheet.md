# 现场 Demo · 三个 A 股研究示例

演示前应使用现场环境重新运行 `scripts/demo_cheatsheet.py`。本表不预写审计结论，因为数据、缓存、预计算报告和模型状态都可能变化。

| 标的 | 名称 | 研究重点 | 现场先检查 |
|---|---|---|---|
| `600519.SH` | 贵州茅台 | 复权、分红、因子和流动性风险 | 数据状态、六项研究能力、来源标签 |
| `300750.SZ` | 宁德时代 | 成长因子、波动、流动性和指数权重变化 | 数据状态、六项研究能力、来源标签 |
| `601318.SH` | 中国平安 | 分红、股票池和风险证据 | 数据状态、六项研究能力、来源标签 |

## 运行事实

- 当前真实研究只支持 A 股。其他市场返回 `insufficient-evidence`。
- 每个真实请求运行四个在线 QuantSkills、一个项目内指数权重变化研究，并读取 HPO 预计算结果。
- 在线 Skill 和单个 Agent 最多 120 秒；整个请求最多 600 秒。
- LLM 在 Volcengine Ark 上显示为 **DeepSeek V4 Pro**，`LLM_MODEL` 填活动 Endpoint ID。
- A2A 服务支持 Agent Card、SSE 和可选 Bearer 鉴权。

## 来源说明

- `live`：本次新取数据。
- `cache`：内容哈希核验通过的缓存。
- `precomputed`：提交号和数据哈希可核验的报告。
- `mock`：离线开发结果，不能作为真实证据。
- `insufficient-evidence`：缺少必要证据，不能称为通过。

真实来源失败时不会改成 mock。现场先说明当前来源和状态，再讲审计发现。没有审计标记不代表标的一定可靠。

## 六项研究能力 ID

`corporate-action-adjustment-auditor`、`survivorship-universe-auditor`、`portfolio-liquidity-stress-test`、`project-index-weight-change-study`、`factor-ranking-sage`、`model-hpo-evidence-driven`。

## 合规提示

只展示证据、分歧和风险范围。不给买卖指令、目标价、收益承诺，也不执行自动交易。
