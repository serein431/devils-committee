# 度小满（参评类别 15）提交说明 · AI 理财认知教练

> 方向：引导用户理解证据，不给操作答案。当前生成示例会保留实际来源标签；默认 mock 只用于本地开发。

## 1. 目标用户
面向想理解股票研究材料、但不熟悉量化术语的初学者。产品把多头、空头、宏观和风险理由分开呈现，再说明哪些证据缺失或受到审计质疑。

## 2. 引导方式和限制
用户输入一个 A 股问题后，四个 Agent 分别阅读同一批证据，Audit Agent 检查选择偏差、数据问题和过拟合，Chair 只汇总共识、分歧和风险范围。
产品不给买卖指令、目标价、收益承诺，也不执行自动交易。所有公开文本经过 `backend/compliance.py` 检查。

常见审计状态的人话说明：
- `pass`：现有审计结果没有指出问题，但这不代表以后不会出现风险。
- `selection_bias`：小心：这像“只把考了高分的同学拿出来吹，输的都不提”——样本被挑过了，看起来的规律可能是假的。
- `bad_data`：小心：这条用的价格数据本身有问题（好比体重秤没归零就称），先把数据修对，再谈结论。
- `suspected_overfit`：小心：这像“把这次的答案背下来考试”，换一套题就不灵——不是真规律，是凑出来的。
- `thin_data`：证据太少：既不能信、也不能一口否掉，先别当真，等更多数据。

## 3. 技术资源
- 模型：Volcengine Ark 上显示为 **DeepSeek V4 Pro**；`LLM_MODEL` 填活动 Endpoint ID。
- 数据：PandaData 历史数据；当前真实研究只支持 A 股，其他市场返回 `insufficient-evidence`。
- Skills：真实请求每次运行四个在线 QuantSkills，并读取两个预计算结果。每个在线 Skill 与单个 Agent 限制 120 秒，整个请求限制 600 秒。
- 接口：A2A、SSE、Bearer 鉴权和 Agent Card 与参评类别 18 共用同一后端。

六个 Skill ID：
- `corporate-action-adjustment-auditor`（在线）
- `survivorship-universe-auditor`（在线）
- `portfolio-liquidity-stress-test`（在线）
- `index-rebalance-event-study`（在线）
- `factor-ranking-sage`（预计算）
- `model-hpo-evidence-driven`（预计算）

## 4. 来源和失败处理
- `live` 是本次新取的数据，`cache` 是内容哈希校验通过的本地数据。
- `precomputed` 是与当前提交号和数据哈希相符的因子或 HPO 报告。
- `mock` 只服务于离线开发，不能用于证明真实研究已经完成。
- 缺失证据标为 `insufficient-evidence`。真实数据、模型或 Skill 失败时不会改成 mock。

## 5. 当前本地生成示例
- 标的：`600519.SH`
- 数据状态：`success`
- 来源：`mock`
- 论据数：`4`；审计标记数：`0`
- Bull：`pass`，来源 `mock`
- Bear：`pass`，来源 `mock`
- Macro：`pass`，来源 `mock`
- Risk：`pass`，来源 `mock`

> 本内容由多智能体辩论生成，仅供学习与研究，不构成任何投资建议；不含买卖操作、目标价或收益承诺。历史/缓存数据不代表未来表现。

## 6. 三个演示标的
`600519.SH`、`300750.SZ`、`601318.SH`。演示前按实际运行模式重跑，不预先承诺审计结论。

## 7. 本地与真实环境
默认开发可用 mock。真实环境要求 Python 3.12 和 `requirements-real.txt`：
```bash
python3.12 -m venv .venv-real
.venv-real/bin/pip install -r requirements-real.txt
git submodule update --init --recursive
.venv-real/bin/python scripts/setup_real.py --check
```

## 8. 完成情况与人工事项
- 本地离线服务、A2A、SSE 和教练页面可由仓库代码运行。
- 合规检查目前包含 8 类规则。
- 团队姓名与分工：`需人工填写`。
- 真实用户试用人数、原话和改动记录：`待完成`。
- 公网访问地址：`待完成`。
- 演示视频及链接：`待完成`。
