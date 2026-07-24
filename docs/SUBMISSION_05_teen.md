# 智能少年（参评类别 05）提交说明

## 项目特点

Devil's Committee 不替用户作投资决定。它把多头、空头、宏观和风险理由分开，再让 Audit Agent 检查数据、样本选择和过拟合。最后只显示共识、分歧、证据不足和风险范围。

产品中的专业词会配人话说明，例如把选择偏差解释成“只看留下来的赢家”，把过拟合解释成“背住一套答案，换题就失效”。这部分可以由本地代码演示，不需要真实凭证。

## 当前可核验内容

- 默认 mock 环境可在本地运行页面、A2A 和 SSE。
- 真实研究设计为 A 股范围，使用 PandaData、四个在线 QuantSkills 和两个预计算结果。
- 固定示例为 `600519.SH`、`300750.SZ`、`601318.SH`。
- 所有公开文本禁止买卖指令、目标价和收益承诺，也不执行自动交易。

以上只说明仓库中的代码和文档，不代表真实凭证联调、公网部署或真人试用已经完成。

## 技术说明

- LLM 通过 Volcengine Ark 调用，显示名称是 DeepSeek V4 Pro；`LLM_MODEL` 填活动 Endpoint ID。
- 真实数据来自 PandaData。每个真实请求在线运行 `corporate-action-adjustment-auditor`、`survivorship-universe-auditor`、`portfolio-liquidity-stress-test`、`index-rebalance-event-study`。
- `factor-ranking-sage` 和 `model-hpo-evidence-driven` 读取预计算报告。
- 在线 Skill 与单个 Agent 限制 120 秒，整个请求限制 600 秒。
- 来源分为 `live`、内容哈希核验后的 `cache`、`precomputed`、`mock`；缺少证据用 `insufficient-evidence`。真实失败不改成 mock。
- 接口提供 A2A、SSE、Bearer 鉴权和 Agent Card。

## 仍需人工填写

- 参赛者姓名、年龄、学校或其他身份信息：`需人工填写并核验`。
- 每位成员实际完成的工作：`需人工填写`。
- 真实用户试用人数、原话、授权和改动记录：`待完成`。
- 现场演示视频或提交链接：`待完成`。
- 若参评要求 Expo 专用幻灯片：`待完成`。仓库现有 HTML 演示稿不能证明该材料已完成。
- 封面图：`待完成`。仓库中未发现可核验的封面图片文件。

不要为了故事效果编写年龄、团队关系、试用反馈或现场反应。提交前应由团队逐项确认。
