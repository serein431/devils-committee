# PandaAI 真实模型、数据与 QuantSkills 接入设计

日期：2026-07-24

状态：已确认范围，等待书面方案审阅

项目：Devil's Committee

## 1. 背景

项目目前已经具备 A2A、SSE、多 Agent 辩论、独立审计、风险检查、离线数据和测试基础，但真实模式仍有明显缺口：模型尚未验证官方 Endpoint，PandaData 只有日线入口，两个 QuantSkills 审计器之外的大部分结果仍由内部启发式计算生成，真实模式失败时还会退回模拟数据。

官方要求包括公开可调用的 A2A Remote Agent、完整 Agent Card、DeepSeek V4 Pro、至少三个示例任务、清晰可解释的输出、授权数据、风险提示和不超过 20 分钟的总响应时间。项目选择先完整支持 A 股；港股和美股输入暂时返回真实数据证据不足。

## 2. 目标与非目标

### 目标

- 使用火山方舟 OpenAI 兼容接口调用官方 DeepSeek V4 Pro Endpoint。
- 使用 `panda_data==0.0.12` 获取真实 A 股行情、复权、分红、指数成分和因子数据。
- 接入四个在线 QuantSkills 和两个预计算 QuantSkills。
- 每条结论都能追溯到数据集、Skill 结果和运行状态。
- 真实模式失败时明确返回证据不足，不用模拟结果冒充真实结果。
- 准备三个可重复执行的 A 股示例任务。
- 保留离线模式用于测试，但所有对外结果必须明确标注 `mock`、`live`、`cache` 或 `insufficient-evidence`。

### 非目标

- 本次不完整支持港股、美股、期货和期权。
- 不接入 QuantSkills 组织下的全部仓库。
- 不在每次在线请求中训练模型或执行参数搜索。
- 不提供买卖指令、目标价、收益承诺或自动交易能力。

## 3. 运行环境与配置

真实运行环境统一使用 Python 3.12。当前 Python 3.13 环境不适合 `panda_data==0.0.12` 的 `numpy<2` 依赖组合。

依赖分为两组：

- `requirements.txt`：FastAPI、HTTP 客户端和离线测试所需基础依赖。
- `requirements-real.txt`：引用基础依赖，并固定 `panda_data==0.0.12`、DuckDB、PyArrow、Pandas、NumPy 兼容版本及六个 QuantSkills 的运行依赖。

真实配置继续从被 Git 忽略的 `.env` 读取：

```text
LLM_MODE=openai
LLM_PROVIDER=volcengine-ark
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_API_KEY=<secret>
LLM_MODEL=<DeepSeek V4 Pro Endpoint ID>
LLM_MODEL_LABEL=DeepSeek V4 Pro

DATA_MODE=panda
DEFAULT_USERNAME=<secret>
DEFAULT_PASSWORD=<secret>
JAVA_SERVICE_BASE_URL=http://pandadata.pandaaiquant.com

SKILL_MODE=cli
QUANTSKILLS_DIR=./vendor/quantskills
```

日志、健康接口、Agent Card、A2A 响应和测试快照均不得包含密钥、账号、密码或请求头。

## 4. 系统结构

一次研究请求按以下顺序执行：

1. 请求解析器识别 A 股代码、问题、日期范围和可选的组合参数。
2. 数据模块构建一份 `MarketDataBundle`，优先读取真实缓存，缺失时请求 PandaData。
3. 四个在线 QuantSkills 并行读取同一数据包，返回统一 `SkillResult`。
4. 两个预计算 QuantSkills 读取带日期、配置和文件哈希的研究报告。
5. Bull、Bear、Macro、Risk Agent 只能引用已经存在的 Skill 结果。
6. Audit Agent 检查论据是否存在数据缺失、选择偏差、坏数据或过拟合迹象。
7. Chair Agent 汇总共识、未解决分歧和风险边界。
8. 合规模块检查全部对外文本，并附统一风险提示。

模型只负责解释和表达，不负责生成新的价格、收益率、财务数字或 Skill 结论。即使模型服务不可用，系统也必须返回结构化数据报告。

## 5. 数据格式

### 请求

```json
{
  "symbol": "600519.SH",
  "question": "贵州茅台当前有哪些看多和看空依据？",
  "start_date": "20240101",
  "end_date": "20260724",
  "portfolio_value": null,
  "spread_bps": null
}
```

### MarketDataBundle

数据包包含：

- 日线行情：开盘、最高、最低、收盘、前收盘、成交量、成交额、交易状态。
- 复权信息：复权因子及可取得的前后复权行情。
- 公司行为：现金分红及与复权检查有关的记录。
- 股票池信息：历史指数成分、证券上市和退市状态，以及接口可提供的生命周期字段。
- 因子数据：因子值、日期、证券代码，以及计算未来收益标签所需行情。
- 元数据：PandaData 方法名、请求参数、获取时间、日期范围、行数、来源状态和 SHA-256。

原始表保存为 Parquet；元数据和索引保存为 JSON。缓存键由方法名、参数、SDK 版本和数据版本共同生成。不同 Agent 只接收文件路径、摘要和哈希，不重复请求同一数据。

### SkillResult

```json
{
  "skill_id": "corporate-action-adjustment-auditor",
  "mode": "live",
  "status": "success",
  "duration_ms": 1840,
  "dataset_hashes": ["..."],
  "assumptions": [],
  "metrics": {},
  "findings": [
    {
      "claim": "复权价格与分红记录一致",
      "evidence_refs": ["daily", "adj_factor", "dividend"],
      "confidence": 0.91
    }
  ],
  "warnings": []
}
```

`status` 只允许 `success`、`insufficient-evidence` 和 `error`。`mode` 只允许 `live`、`cache`、`precomputed` 和 `mock`。

## 6. 六个 QuantSkills

### 每次请求在线执行

1. `skill-corporate-action-adjustment-auditor`
   - 输入：原始行情、复权行情或因子、分红记录。
   - 输出：异常跳空、复权不一致和缺失公司行为记录。

2. `skill-survivorship-universe-auditor`
   - 输入：历史成员、上市退市时间、收益和可取得的退市收益字段。
   - 输出：存活偏差证据或缺失字段说明。缺少退市收益时不得判定通过。

3. `skill-portfolio-liquidity-stress-test`
   - 输入：真实成交额、波动率和用户提供的持仓金额、价差。
   - 输出：成交天数、冲击估计和流动性警告。用户未提供的持仓金额或价差必须标为演示假设。

4. `skill-index-rebalance-event-study`
   - 输入：历史指数成分变化、股票行情和指数行情。
   - 输出：事件窗口收益、成交量变化和数据不足说明。

### 提前计算，在线读取

5. `skill-factor-ranking-sage`
   - 使用真实因子表和未来收益标签，生成因子排名、样本数、训练区间、验证区间和样本外指标。

6. `skill-model-hpo-evidence-driven`
   - 离线执行参数搜索，保存配置、搜索范围、随机种子、训练与验证指标、最佳参数和失败实验。

预计算报告必须记录生成日期、代码提交、数据哈希和完整参数。过期或哈希不符时状态改为 `insufficient-evidence`，不能继续作为当前证据引用。

## 7. 失败处理与时间限制

- PandaData 请求失败：若有匹配参数的真实缓存，使用缓存并标为 `cache`；否则返回 `insufficient-evidence`。
- 禁止在 `DATA_MODE=panda` 时静默退回模拟数据。
- 单个在线 Skill 最长运行 120 秒；超时只影响该 Skill，其他结果继续返回。
- 整个研究请求内部预算为 10 分钟，为官方 20 分钟限制保留余量。
- DeepSeek 调用失败：返回 Skill 原始摘要、审计结果和固定风险提示，不生成伪造文本。
- 返回空表时先检查代码格式、日期范围、权限和必填参数，再确定是数据缺失还是服务异常。
- 港股、美股或无法识别的市场输入返回 `insufficient-evidence`，并说明当前只支持 A 股真实研究。
- 异常响应只返回错误类别和用户可采取的动作，不暴露内部路径或服务响应正文。

## 8. 三个示例任务

1. `600519.SH`：复权、分红、因子排名和流动性研究。
2. `300750.SZ`：成长因子、波动、流动性和指数事件研究。
3. `601318.SH`：金融行业、分红、股票池和风险研究。

每个示例保存自然语言输入、结构化请求、PandaData 查询清单、Skill 运行记录、最终 A2A 输出和风险提示。真实调用记录必须删除凭证和请求头。

## 9. 测试方案

### 默认测试

- 数据解析：列名、日期顺序、空表、重复行、缺失值和代码格式。
- 缓存：参数匹配、哈希校验、过期状态和真实模式禁止模拟回退。
- Skill 契约：六个适配器的输入、输出、超时和错误映射。
- Agent 引用：每条论据必须存在 `skill_id` 和 `evidence_refs`。
- 模型失败：仍返回结构化报告。
- 合规：买卖指令、收益承诺和目标价必须被移除。
- A2A：Agent Card、JSON、SSE、鉴权和错误脱敏。

### 真实测试

真实测试通过 `RUN_LIVE_INTEGRATION=1` 单独启用，不进入普通 CI。测试内容包括 DeepSeek 最小回复、PandaData 登录、日线查询、六个 Skill 冒烟检查和三个 A 股完整请求。

上线后使用公网地址运行 `scripts/smoke_a2a.py`。Agent Card URL、服务 URL、鉴权方式和 `PUBLIC_URL` 必须一致。

## 10. 部署与提交材料

最终服务使用 Python 3.12 部署到持续在线的 Linux 主机，通过 HTTPS 反向代理公开：

- `GET /.well-known/agent-card.json`
- `GET /healthz`
- `POST /a2a`
- `POST /a2a?stream=1`

服务使用进程守护和自动重启，缓存目录与代码目录分开，日志不保存凭证。临时隧道只用于联调，不作为最终评审地址。

文档需同步更新 Agent Card、PandaAI 说明、度小满说明、Qoder 两项文书、智能少年真人反馈、小红书内容记录、Skills 清单和三个示例结果。Qoder 截图或录屏仅作为可选补充，不列为已知硬要求。

## 11. 完成标准

- DeepSeek V4 Pro 真实回复通过。
- PandaData 真实日线和所需扩展数据接口通过。
- 四个在线 Skill 和两个预计算 Skill 均有真实运行证据。
- 三个 A 股示例任务可从 A2A 入口重复执行。
- 真实模式不再把失败隐藏为模拟成功。
- 后端、前端、合规和 A2A 测试全部通过。
- 公网 Agent Card 和 A2A 服务可访问，响应时间符合要求。
- 提交文档准确区分真实数据、缓存、预计算、假设和证据不足。
