# 反方 · The Devil's Committee — AI 投资辩论庭

> 别人给你一个**结论**——买这个、涨那个。我们把它**反转**：让 Bull / Bear / Macro / Risk
> 四个 AI 当面吵架，一个**审计 AI 专门拆台**（抓存活/选择偏差、坏数据、过拟合），
> 主持收敛成一张 **「分歧地图 + 审计印章 + 风险边界」**。它不给买卖，教你自己当裁判。
>
> 一个引擎，两张脸：对 **18 PandaAI** 是 A2A 自托管后端；对 **15 度小满** 是理财认知教练前端。

**现在就能跑（零凭证，全离线）：**
```bash
cd devils-committee
./run.sh            # 或： python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
                    #       .venv/bin/python -m uvicorn backend.a2a_server:app --port 8080
# 打开 http://localhost:8080/         → 教练前端（15 的脸）
# GET  /healthz                       → 健康检查（18 命脉：一直在线）
# GET  /.well-known/agent-card.json   → A2A Agent Card（18 联调入口）
# POST /a2a  {"topic":"600519 多空理由"}  → 结构化辩论结果（加 ?stream=1 走 SSE）
```

---

## 六段式（每条赛道的说明文档都用这个骨架，只换侧重）

**1. 情境** — 一个理财小白面对一个标的，网上信息一边倒：全是"买/涨"的结论，看不到反方是谁、风险在哪、那条论据是不是挑出来的。

**2. 输入** — 一句自然语言提问（"帮我理解 600519 现在多空双方的理由和风险"）+ 平台历史数据（panda_data，仅研究）。

**3. 转换** — 四个 Agent **并行取证**（各调真实 QuantSkills），审计 Agent **独立复核每一条**并能**打回**弱论据，主持 Agent 收敛。这是**真协作，非串联**（见 `backend/orchestration.py`）。

**4. 输出** — 一场可读的辩论（正/反方逐条附证据）+ 一张分歧地图（哪些共识、哪些仍吵）+ 审计印章（通过 / 选择偏差 / 坏数据 / 过拟合 / 证据不足）+ 明确的风险边界。

**5. 证据** — 现场对任一标的真机跑；`tests/examples/` 存 ≥3 个示例任务，且**审计会辨别**（一个标 bad_data、一个标 overfit 并触发打回、一个完全通过——不是硬编码 gotcha）；真小白试用反馈见 `docs/user-tests/`。

**6. 边界** — 不荐股、不宣称收益、不给目标价；一切对外输出**强制过 `backend/compliance.py`**，附风险提示，标注 AI 不确定项。

---

## 架构（同一引擎，两张脸）

```
用户/评委提问（自然语言，一个标的）
        │
   A2A Server (backend/a2a_server.py) ── /.well-known/agent-card.json · /healthz · /a2a(SSE)
        │  DebateOrchestrator.run(topic)          [全局预算 18min < 20min 硬上限]
        ├─ Bull ─┐
        ├─ Bear ─┤  并行取证 asyncio.gather（各调 QuantSkills / panda_data）
        ├─ Macro ┤
        └─ Risk ─┘
             ▼
        Audit Agent  ── 独立复核每条论据，可打回（survivorship / data-quality / hpo 审计）
             ▼
        Chair Agent  ── 收敛：共识 / 未解分歧 / 风险边界
             ▼
        compliance.enforce()  ── 禁买卖/收益承诺，强制免责，保留审计标记
        ├──────────────┬───────────────
        ▼              ▼
   A2A JSON(18)   教练前端(15)  分歧地图 + 审计印章 + 边界
```

| 组件 | 满足赛道 | 说明 |
|---|---|---|
| `backend/a2a_server.py` | 18 | Agent Card + A2A + SSE + 健康检查 + ≤20min |
| `backend/agents.py` · `orchestration.py` | 18 | 对抗辩论 + **独立审计 + 打回** = 真协作 |
| `backend/skills/` | 18 | QuantSkills + panda_data 封装（mock↔real 一个开关） |
| `backend/compliance.py` | 15 / 18 | 合规闸：禁买卖/收益，强制风险提示 |
| `web/index.html` | 15 | 教练 UX：辩论视图 / 分歧地图 / 审计印章 / 边界 |
| `docs/qoder-process/` | 04 | Qoder 多智能体开发证据 |
| `docs/build-in-public/` | 07 | 小红书 Build in Public 素材 |
| `docs/user-tests/` | 05 / 15 | 真小白试用记录 |
| `tests/` | 18 | ≥3 示例任务 + 合规 + 端到端回归 |

---

## 用到的真实 QuantSkills（github.com/quantskills，2026-07-23 核实）

**取证（Bull/Bear/Macro/Risk）**：`skill-factor-ranking-sage` · `skill-residual-guided-factor-selection` · `skill-us-sector-rotation` · `skill-portfolio-liquidity-stress-test` · `skill-index-rebalance-event-study` · `skill-holder-structure-scan` · `skill-dalio-all-weather` · `skill-templeton-global-contrarian` · `skill-corporate-action-adjustment-auditor`

**审计（杀手锏）**：`skill-survivorship-universe-auditor`（选择/存活偏差）· `skill-intraday-data-quality-auditor`（坏数据）· `skill-model-hpo-evidence-driven`（过拟合）

数据：`panda_data==0.0.12`，`get_stock_daily(symbol=[...], start_date, end_date, ...)`，仅历史。

> QuantSkills 是 CLI 工具（`python scripts/<name>.py --input in.csv --out out.json`）。
> 本仓库 `SKILL_MODE=mock` 时用**仿真真实 JSON 契约**的确定性输出离线跑通全流程；
> `SKILL_MODE=cli` 时调用克隆的真实 skill（`backend/skills/runner.py::_run_cli`）。

---

## 三个模式开关（mock↔real 都是配置，不是重写）

| 变量 | 默认 | real 值 | 需要 |
|---|---|---|---|
| `LLM_MODE` | `mock` | `openai` | DeepSeek Key（飞书群，7/23 起底座不锁死可换任意模型） |
| `DATA_MODE` | `mock` | `panda` | panda_data 账号（飞书群 7 天窗口） |
| `SKILL_MODE` | `mock` | `cli` | 克隆 QuantSkills 到 `QUANTSKILLS_DIR` |

`cp .env.example .env` 后填入即可切换。所有 `TODO(feishu)` 标出需群内确认的确切签名。

拿到飞书凭证后走**最后一公里**：`python scripts/setup_real.py`（就绪矩阵，看哪项齐了）→ `--check`（联网探活 LLM/panda）→ `--enable llm data skill`（一键切 `.env` 模式）。

**`SKILL_MODE=cli` 已接入现场辩论的两个真审计器**（`scripts/fetch_quantskills.sh` 克隆后即用）：
- 因子论据 → 真 `skill-survivorship-universe-auditor`（选择/存活偏差）
- 价格证据 → 真 `skill-corporate-action-adjustment-auditor`（未复权跳空/坏数据）

每条 verdict 带 `provenance`（`mock` / `mock-fallback` / `real-cli`），`meta.audit_engine` 汇总。mock 模式喂给真 skill 的输入明确标 `mock-synthetic`，不冒充真域。
**过拟合审计（`skill-model-hpo-evidence-driven`）暂未 cli 接入**：它需 numpy/pandas/sklearn/lightgbm/torch + 真因子面板（`DATA_MODE=panda`），mock 数据喂它只会产生无意义结果——故保持 mock 启发式，等真数据到位再接。

**两个 Agent Card 广告的技能都真的实现**：`debate_case`（完整辩论）与 `audit_claims`（只返回逐条审计 verdict）。

---

## 上线（18 命脉：评审期稳定在线 + ≤20 分钟）

见 `docs/service_checklist.md`。要点：公网可达（Cloudflare Tunnel / VPS）、`/healthz` + 进程守护自动拉起、Agent Card 公网可访问且 URL 与 `PUBLIC_URL` 一致、准备备份部署、7 天数据落本地缓存走缓存联调。

```bash
# 起服务
PUBLIC_URL=https://your-tunnel.example./run.sh
# 另开一终端把它暴露到公网（需你们的 Cloudflare 账号登录）
scripts/expose_tunnel.sh 8080
# 终审前对着公网 URL 一跑即知是否就绪（healthz/card/两技能/SSE/鉴权全查）
python scripts/smoke_a2a.py --url https://your-tunnel.example [--token SECRET]
```

---

## 现场 Demo

```bash
.venv/bin/python scripts/demo.py 600519          # 终端排练器：真引擎 + 旁白节奏（也是 UI 翻车时的稳态兜底）
.venv/bin/python scripts/demo.py TSLA            # 「审计全部放行」剧情，证明它会分辨
```
逐秒编舞、评委席差异化侧重、兜底预案见 `docs/demo_script.md`。

## 提交文档（赛道 18）

```bash
.venv/bin/python scripts/gen_submission.py      # → docs/SUBMISSION_18.md（PandaAI 清单）
.venv/bin/python scripts/gen_submission_15.py   # → docs/SUBMISSION_15.md（度小满 8 问）
```
均从真实运行输出生成（示例/Skills 清单/人话/合规规则皆实跑），`TODO` 处填对外信息即可提交。

## 测试

```bash
.venv/bin/python -m pytest -q      # 后端：合规/端到端/示例/真实skill/LLM/数据/健壮性/安全（54 检查）
./scripts/test_frontend.sh         # 前端：jsdom 加载 index.html，验证渲染/审计标红/XSS转义/双视图（13 检查）
```

---

## 合规（不是装饰，是 15 计分项 + 18 失格红线）

一切对外输出经 `compliance.enforce()`：正则拦截 `建议买入/卖出`、`目标价`、`必涨/稳赚`、`收益率 N%`、`strong buy` 等；强制附免责声明；**审计标记保持可见**（诚实是加分，不是要藏的东西）。

> 仅供学习与研究，不构成任何投资建议。历史/缓存数据不代表未来表现。
