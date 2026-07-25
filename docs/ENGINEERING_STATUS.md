# 工程现状总览（回来先看这页）

> 反方 · The Devil's Committee — AI 投资辩论庭。一个产品打 5 赛道 + 主题 E。
> 这份是"建了什么 / 测了什么 / 还差什么"的单页索引。策略见 `../../flagship_plan/MASTER_PLAN.md`。

## 一句话状态
离线零凭证即可端到端跑通（`./run.sh` → http://localhost:8080/）。软件、五赛道提交材料、
现场 demo 准备、offline→real 切换路径**都已就绪并测试覆盖**。剩下的是人工项（见末尾）。

## 建了什么
- **引擎**：六 Agent（Bull/Bear/Macro/Risk 并行取证 + Audit 独立复核可打回 + Chair 收敛）。`backend/`
- **A2A 服务**：`/healthz` · `/.well-known/agent-card.json` · `/a2a`(JSON+SSE)。两个广告技能 `debate_case` / `audit_claims` 都真实现。FastAPI，18 分钟预算 + per-agent 超时。
- **两个真实 QuantSkills 审计器接入**（`SKILL_MODE=cli`）：survivorship（选择偏差）+ corporate-action（坏数据），verdict 带 `provenance`（mock/real-cli）。过拟合审计待真数据（需 numpy/torch + 面板）。
- **教练前端**（`web/index.html`）：**量化终端风**（Bloomberg 气质，等宽/密集/涨跌色）——委员会竞技场 + 每个 Agent 的内联数据可视化（因子 IC 柱/流动性冲击/事件 CAR diverging）+ 审计控制台（严重度环 + `REAL·QuantSkills` provenance 徽章 + 驳回动效）+ diverging 分歧地图 + 引擎流水线面板 + 专家/小白双视图。色板经 dataviz 验证器校验（CVD ΔE 15.1）。
- **合规**：`backend/compliance.py` 代码级拦买卖/收益/目标价 + 强制免责 + `meta.gives_investment_advice:false` 机器可校验。
- **数据缓存**：7 天窗口内预热（`scripts/warm_cache.py`），终审走缓存不碰 panda_data。
- **三模式开关**：`LLM_MODE`/`DATA_MODE`/`SKILL_MODE`，mock↔real 是填 `.env`（`scripts/setup_real.py` 一键切）。

## 测了什么（67 项自动化检查）
- 后端 `pytest`：54 项，**91% 覆盖**——合规 / 端到端 / ≥3 示例 / 真实 skill CLI / LLM 单元+全链路集成 / 数据缓存 / panda 灵活解析 / 服务健壮性 / 安全（鉴权/错误脱敏/XSS）/ 配置解析 / 审计边界（thin_data）。
- 前端 `./scripts/test_frontend.sh`：24 项（jsdom）——渲染 / 数据可视化 SVG / 审计标红+严重度环 / REAL provenance 徽章 / XSS 转义 / diverging 分歧地图 / 双视图。
- 公网就绪：`scripts/smoke_a2a.py --url https://devils.corvusapi.org` 16 项（对运行中服务发真实 HTTP）。

## offline→real 已排的雷（拿凭证切换时不会踩）
`.env` 行内注释被当值 · LLM 响应异常崩溃 · LLM 全链路未验 · panda 列名写死/空结果崩 · `sh600519`/`BUY` 输入识别错 · 前端 XSS · 鉴权时序 · 错误泄露内部路径。**均已修 + 测试锁定。**

## 关键脚本
| 脚本 | 用途 |
|---|---|
| `run.sh` | 一键起服务（离线 demo） |
| `scripts/demo.py` | 终端排练器 / UI 翻车兜底 |
| `scripts/demo_cheatsheet.py` | 标的→审计结论速查 + 主持话术 |
| `scripts/setup_real.py` | real 模式就绪检查 + 一键切 `.env` |
| `scripts/warm_cache.py` | 7 天窗口内预热数据缓存 |
| `scripts/fetch_quantskills.sh` | 克隆真实 QuantSkills |
| `scripts/expose_tunnel.sh` | Cloudflare Tunnel 上公网 |
| `scripts/smoke_a2a.py` | 上线后公网就绪自检 |
| `scripts/gen_submission*.py` | 生成 18/15 提交稿 |

## 还差什么（只有你们能做）
1. 进 PandaAI 飞书群领 **DeepSeek Key / panda_data 凭证 / 测试环境**（→ `setup_real.py --check --enable ...`）
2. **今天发第一条小红书**（草稿 `docs/build-in-public/note-01.md`）
3. 完成 Qoder 两项文书；如有真实开发记录，可整理到 `docs/qoder-process/` 作为补充
4. 拉 **2–3 个真小白**试用录反应（`docs/user-tests/`）
5. **看主题 E Reverse 官方视频**确认方向
6. 公网上线 + `smoke_a2a.py` 自检
7. 找业务/合规导师问 15 红线
8. 开页面做**视觉验收**（双视图/抓假动效手感）

> 提交材料索引见 `docs/README.md`；每赛道底稿 `docs/SUBMISSION_*.md`。
