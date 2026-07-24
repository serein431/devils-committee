# 现场 Demo 脚本

目标是在三分钟讲清产品用途。真实研究请求最长可用 600 秒，因此上台前应预热数据并确认缓存；不要承诺每次都在三分钟内完成，也不要预写某个标的一定出现哪种审计结论。

## 开场前检查

- 公网地址：`待完成`。未完成公网部署时，只能演示本地地址并如实说明。
- `GET /healthz`、Agent Card、A2A JSON、SSE 和 Bearer 鉴权均按现场环境检查。
- 确认页面显示的来源：`live`、`cache`、`precomputed` 或 `mock`。
- 真实环境显示模型名称 **DeepSeek V4 Pro**；`LLM_MODEL` 使用活动 Endpoint ID。
- 真实研究只支持 A 股。准备 `600519.SH`、`300750.SZ`、`601318.SH` 三个示例。
- 终端备用命令：`.venv/bin/python scripts/demo.py 600519.SH --pace 0.7`。

## 第一段：用户为什么需要它

台词建议：

> 普通研究工具常先给结论。我们先把多头、空头、宏观和风险理由分开，再让一个独立 Agent 检查证据。

输入一个固定 A 股示例，或请评委从三个已准备标的中选择。页面开始请求后，说明服务可通过 A2A 调用，也能用 SSE 接收阶段事件；启用鉴权时需要 Bearer Token。

## 第二段：证据从哪里来

台词建议：

> 每个真实请求会运行四个在线 QuantSkills：公司行动复权、股票池存活、流动性压力和指数调整事件。另外两个 Skill 读取因子筛选与 HPO 的预计算报告。

六个提交用 Skill ID：

- `corporate-action-adjustment-auditor`
- `survivorship-universe-auditor`
- `portfolio-liquidity-stress-test`
- `index-rebalance-event-study`
- `factor-ranking-sage`
- `model-hpo-evidence-driven`

在线 Skill 和单个 Agent 的限制是 120 秒，整个请求限制是 600 秒。

## 第三段：怎么读审计结果

先看数据和 Skill 的 `mode` 与 `status`：

- `live`：本次从 PandaData 新取数据。
- `cache`：读取内容哈希核验通过的本地数据。
- `precomputed`：读取与当前构建和数据哈希相符的报告。
- `mock`：离线演示结果，不能当作真实证据。
- `insufficient-evidence`：证据缺失，不能说成通过。

台词建议：

> 审计结果只说明当前证据有没有发现问题。没有标记不等于标的一定可靠；证据不足也不等于通过。真实来源失败时，系统不会用 mock 补上。

## 收尾

> 它不告诉你买不买，只把证据、分歧和风险范围摆出来，帮助你自己判断。

页面最后必须有风险提示。口头也不要给买卖指令、目标价、收益承诺，不要演示自动交易。

## 失败处理

1. 公网访问失败：切到本地服务，并明确说明公网部署仍待完成。
2. 页面失败：切终端演示同一后端，不把录屏说成实时结果。
3. PandaData 或在线 Skill 失败：展示错误或 `insufficient-evidence`，不要改成 mock 后称为真实运行。
4. 评委给出非 A 股标的：说明当前真实研究范围只含 A 股，并改用三个固定示例之一。
5. 预计算报告缺失或哈希不符：说明两个预计算 Skill 没有可用证据，不宣称审计通过。

## 人工事项

- 演示人姓名与分工：`需人工填写`。
- 公网地址：`待完成`。
- 演示视频及链接：`待完成`。
- 真实凭证环境下的三条脱敏记录：`待完成`。
