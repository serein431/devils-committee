# Qoder 多智能体开发证据（04 · 多智能体协作占 30% 权重）

> ⚠️ 非平凡的额外动作：必须**真用 Qoder 的多智能体并行开发**并留证据，
> 不是把它当代码补全/编辑器。叙事钩子：**用一支 AI 团队，造另一支 AI 团队。**

## 要捕捉的证据（顺手录屏，别事后补）
- [ ] Qoder 里**多个 agent 角色并行**开发本仓库的截图/录屏（如：前端 agent 写 `web/`、后端 agent 写 `backend/orchestration.py`、测试 agent 写 `tests/`、评审 agent review）。
- [ ] 一次"人机协作工作流"的完整片段：人给意图 → 多 agent 分工 → 汇总产出。
- [ ] 对照本项目：我们做的产品本身就是"六个 Agent 协作 + 审计"，用 Qoder 的多 Agent 造它 = 主题自洽。

## 04 两问回答要点
1. **解决什么问题 / 目标用户**：给理财小白的反方教练（见根 README 六段式）。
2. **人机协作工作流**：AI 承担哪些角色、如何分工——用本目录的录屏 + 下表佐证。

## 分工映射（把录屏对上下面这张表）
| Qoder Agent 角色 | 负责本仓库 | 产出证据 |
|---|---|---|
| 后端/架构 | `backend/agents.py` `orchestration.py` `a2a_server.py` | |
| 数据/技能 | `backend/skills/*` | |
| 前端/产品 | `web/index.html` | |
| 测试/评审 | `tests/*` | |
