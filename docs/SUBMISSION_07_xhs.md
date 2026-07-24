# 小红书 Build in Public（参评类别 07）说明

仓库中有首帖草稿 `docs/build-in-public/note-01.md`，但没有可核验的已发布 URL 或社区互动记录。本文件只写发布计划，不把草稿说成已经发布。

## 项目介绍

Devil's Committee 是一个面向投资研究初学者的“反方教练”。四个 Agent 分别说明多头、空头、宏观和风险证据，Audit Agent 检查数据、样本选择与过拟合，最后只显示共识、分歧和风险范围。产品不给买卖指令、目标价或收益承诺。

## 发布计划

1. 介绍为什么要让 AI 互相检查，而不是只给一个结论。
2. 展示 `600519.SH`、`300750.SZ` 或 `601318.SH` 的本地流程，并明确标注当次是 `mock`、`live`、`cache` 还是 `precomputed`。
3. 说明真实研究只支持 A 股；证据不足时展示 `insufficient-evidence`，不改成 mock。
4. 发布真实用户试用后，再引用已获许可的原话和实际改动。

## 合规说明

帖子只介绍学习、研究和开发过程。不得发布买卖指令、目标价、收益承诺或自动交易演示。涉及标的时附“仅供学习与研究，不构成投资建议”。

## 帖子中的技术事实

- LLM 通过 Volcengine Ark 调用，显示名称是 DeepSeek V4 Pro；`LLM_MODEL` 填活动 Endpoint ID。
- 真实数据来自 PandaData。每个真实请求在线运行 `corporate-action-adjustment-auditor`、`survivorship-universe-auditor`、`portfolio-liquidity-stress-test`、`index-rebalance-event-study`。
- `factor-ranking-sage` 和 `model-hpo-evidence-driven` 读取预计算报告。
- 在线 Skill 与单个 Agent 限制 120 秒，整个请求限制 600 秒。
- A2A 服务支持 SSE、Bearer 鉴权和 Agent Card。
- `cache` 必须通过内容哈希核验；真实来源失败时返回错误或 `insufficient-evidence`，不能改成 mock。

## 需人工填写

| 项目 | 状态 |
|---|---|
| 团队成员姓名或账号 | `需人工填写` |
| 首帖 URL | `待完成` |
| 后续帖子 URL | `待完成` |
| 社区反馈与回复记录 | `待完成` |
| 真实用户授权内容 | `待完成` |
| 帖子封面图 | `待完成`；仓库中未发现可核验的封面图片 |

只有 URL 能打开并确认内容后，才能把状态改为已发布。
