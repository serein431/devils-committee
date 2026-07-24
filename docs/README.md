# 提交材料索引 · 五赛道 + 主题

一个产品，五条赞助赛道 + 主题 E。每条的提交底稿都在这，人工只需填对外信息 / 补真人证据。

| 赛道 | 底稿 | 生成方式 | 关键人工待办 |
|---|---|---|---|
| **18 PandaAI** | [`SUBMISSION_18.md`](SUBMISSION_18.md) | `scripts/gen_submission.py`（实跑生成） | 公网 URL、GitHub、演示视频、团队联系方式 |
| **15 度小满** | [`SUBMISSION_15.md`](SUBMISSION_15.md) | `scripts/gen_submission_15.py`（实跑生成） | 访问链接、**真实用户使用数据** |
| **04 Qoder** | [`SUBMISSION_04_qoder.md`](SUBMISSION_04_qoder.md) | 手写 | **Qoder 多智能体开发录屏/截图** |
| **05 智能少年** | [`SUBMISSION_05_teen.md`](SUBMISSION_05_teen.md) | 手写 | **2–3 个真小白试用录像 + 原话** |
| **07 小红书** | [`SUBMISSION_07_xhs.md`](SUBMISSION_07_xhs.md) | 手写 | **今天发首帖**，比赛期持续更 + 真回评论 |
| **主题 E Reverse** | [`SUBMISSION_E_reverse.md`](SUBMISSION_E_reverse.md) | 手写 | **看官方视频确认方向能对上** |

## 支撑文档
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — 系统架构、数据流、A2A 清单
- [`service_checklist.md`](service_checklist.md) — 18 命脉：上线/稳定性/联调/提交物/红线
- [`demo_script.md`](demo_script.md) — 现场 3 分钟逐秒编舞 + 评委席差异化 + 兜底预案
- [`demo_cheatsheet.md`](demo_cheatsheet.md) — 标的→审计结论速查 + 主持人话术（`scripts/demo_cheatsheet.py` 生成）
- [`build-in-public/note-01.md`](build-in-public/note-01.md) — 小红书首帖草稿
- [`user-tests/`](user-tests/) — 真小白试用协议 + 记录模板
- [`qoder-process/`](qoder-process/) — Qoder 多智能体开发取证模板

## 人工待办总清单（只有你们能做的）
1. **注册 pandaaiquant.com + 进 PandaAI 飞书群** → 领 7 天数据 / DeepSeek Key / 示例 Agent Card / 测试环境 URL / panda_data 账密。（解锁 real 模式）
2. **今天发第一条小红书**立项帖（07 分数是时间的函数）。
3. **开 Qoder PRO** 并录多智能体开发过程（04 的 30%）。
4. **拉 2–3 个真小白**试用并录反应（05/15/07 最强证据）。
5. **看一遍主题 E Reverse 官方视频**确认方向（现在是推测）。
6. **公网上线**：`scripts/expose_tunnel.sh 8080`（需 Cloudflare 登录）+ 设 `PUBLIC_URL`，然后 `python scripts/smoke_a2a.py --url <公网地址>` 自检 13 项全绿。
7. 找业务/合规导师问 15 红线。
8. 打开教练前端做一次视觉验收（本机 `http://localhost:8080/`）。

> 填了 1 的凭证后，`.env` 切 `LLM_MODE=openai` / `DATA_MODE=panda` / `SKILL_MODE=cli` 即从离线 demo 升级到真数据真模型真审计——都是配置，不是重写。
