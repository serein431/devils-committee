# 反方 · The Devil's Committee

一个面向投资研究初学者的多智能体辩论工具。Bull、Bear、Macro、Risk 四个 Agent 阅读同一批证据并行陈述，Audit Agent 检查选择偏差、公司行动复权、流动性、指数权重变化和模型过拟合；初审后四方针对具体对手论据进行一轮定向交叉质询，Audit 复审回应，Chair 再汇总共识、分歧与风险范围。

项目不给买卖指令、目标价、收益承诺，也不执行自动交易。输出仅供学习与研究。

## 当前能证明什么

- 默认开发环境使用确定性的 `mock`，不需要模型、PandaData 或 QuantSkills 凭证。
- 真实环境需要 Python 3.12、`requirements-real.txt`、Volcengine Ark Endpoint ID、PandaData 账号和 QuantSkills 仓库。
- LLM 通过 Volcengine Ark 调用，页面和状态接口显示名称为 **DeepSeek V4 Pro**；`LLM_MODEL` 必须填写活动提供的 Endpoint ID，不是显示名称。
- 当前真实研究只支持 A 股。港股或其他境外市场会返回 `insufficient-evidence`，不会用 mock 补成结果。
- 每个真实请求运行四个在线 QuantSkills 和一个项目内的指数权重变化研究，并读取 HPO 预计算结果；在线因子研究失败时可读取经过哈希核验的预计算报告。
- 公网服务已部署到 `https://devils.corvusapi.org`，提供 A2A v1 JSON-RPC、Task 查询和 SSE 状态事件。

## 默认开发：离线 mock

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

打开 `http://localhost:8080/` 使用教练页面。常用接口：

```bash
curl http://localhost:8080/healthz
curl http://localhost:8080/.well-known/agent-card.json
curl -X POST http://localhost:8080/a2a \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"demo-1","method":"SendMessage","params":{"message":{"messageId":"input-1","role":"ROLE_USER","parts":[{"text":"研究 600519.SH 的复权、分红、因子和流动性风险"}]},"metadata":{"skill":"debate_case"}}}'
curl -N -X POST http://localhost:8080/a2a \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  -d '{"jsonrpc":"2.0","id":"demo-2","method":"SendStreamingMessage","params":{"message":{"messageId":"input-2","role":"ROLE_USER","parts":[{"text":"研究 300750.SZ 的成长因子、波动和流动性风险"}]},"metadata":{"skill":"debate_case"}}}'
```

长任务会返回 `Task`。流式调用依次发送 `TASK_STATE_SUBMITTED`、`TASK_STATE_WORKING`、结果 artifact 和 `TASK_STATE_COMPLETED`；可使用 `GetTask` 查询，使用 `CancelTask` 取消未结束的任务。

如果设置了 `A2A_BEARER_TOKEN`，调用方还要发送 `Authorization: Bearer <token>`。

## 真实环境

```bash
python3.12 -m venv .venv-real
.venv-real/bin/pip install -r requirements-real.txt
git submodule update --init --recursive
.venv-real/bin/python scripts/setup_real.py --check
```

复制 `.env.example` 为 `.env`，再由人工填写 `LLM_API_KEY`、`LLM_MODEL`、`DEFAULT_USERNAME` 和 `DEFAULT_PASSWORD`。凭证只应保存在本机或部署平台的私密配置中。

真实研究使用 PandaData 历史数据。缓存键由请求方法、参数、SDK 版本和数据版本计算；Parquet 文件另存 SHA-256。读取缓存时会重新核验哈希。

## 六项研究能力

提交材料使用下面六个能力 ID。五项来自 QuantSkills，一项由本项目实现。

| Skill ID | 真实请求中的方式 | 主要用途 |
|---|---|---|
| `corporate-action-adjustment-auditor` | 每次在线运行 | 检查复权与现金分红数据 |
| `survivorship-universe-auditor` | 每次在线运行 | 检查股票池与退市证据 |
| `portfolio-liquidity-stress-test` | 每次在线运行 | 估算流动性压力 |
| `project-index-weight-change-study` | 每次在线运行 | 使用 PandaAI 权重记录日期研究前后收益与成交量 |
| `factor-ranking-sage` | 在线运行，失败时读取预计算报告 | 因子筛选与验证 |
| `model-hpo-evidence-driven` | 读取预计算报告 | 参数搜索与过拟合证据 |

## 来源和状态

- `live`：本次从 PandaData 新取数据，并写入带内容哈希的缓存。
- `cache`：读取此前保存且哈希核验通过的数据。
- `precomputed`：读取提交号、数据哈希和文件清单均可核验的报告。
- `mock`：离线开发用的固定模拟结果，不能当作真实研究证据。
- `insufficient-evidence`：缺少所需字段、记录或预计算报告，不能说成通过。

真实数据、模型或在线 Skill 失败时，程序返回错误或 `insufficient-evidence`，不会改成 mock。响应中的 `meta.modes`、`skills_manifest.results[].mode` 和 `status` 用来说明每条证据来自哪里。

## 请求流程

```text
A2A 请求
  └─ 研究请求解析：只接受当前支持的 A 股代码
      └─ PandaData：live 或经哈希核验的 cache
          ├─ 四个在线 QuantSkills（每个最多 120 秒）
          ├─ 项目内指数权重变化研究
          └─ HPO precomputed 报告（因子研究可在失败时读取预计算报告）
              └─ Bull / Bear / Macro / Risk 首轮并行陈述（单个 Agent 最多 120 秒）
                  └─ Audit 独立初审
                      └─ 四方针对具体论据并行定向回应
                          └─ Audit 复审回应
                              └─ Chair 根据陈述、回应与审计结果汇总
                                  └─ compliance 检查后返回 JSON 或 SSE
```

交叉质询只有一轮，不会重复获取数据或运行 QuantSkills。`Claim` 在原有响应字段之外新增兼容字段：`kind` 区分首轮陈述与回应，`round` 标记轮次，`responds_to` 指向被回应的论据 ID；现有客户端可继续忽略这些新增字段。

整个请求限制为 600 秒。SSE 会持续发送阶段事件，但不会改变同一请求的时间限制。

## 三个固定研究示例

- `600519.SH`：复权、分红、因子和流动性风险。
- `300750.SZ`：成长因子、波动、流动性和指数权重变化。
- `601318.SH`：分红、股票池和风险证据。

示例文件位于 `tests/examples/`。审计结论取决于实际数据、缓存和预计算报告，文档不预写“必定通过”或“必定标记”。

## 测试

统一离线测试默认强制使用 mock，不访问付费服务：

```bash
.venv/bin/python -m pytest -q
./scripts/test_frontend.sh
```

真实联调测试必须由人工明确开启，并使用 Python 3.12 的真实环境：

```bash
RUN_LIVE_INTEGRATION=1 .venv-real/bin/python -m pytest tests/test_live_integration.py -v
```

不要在普通测试或 CI 中放入真实凭证。

## 文档

- `docs/ARCHITECTURE.md`：数据、Skill、Agent 和接口关系。
- `docs/LIVE_INTEGRATION.md`：真实环境准备与脱敏记录。
- `docs/demo_script.md`：现场演示步骤和失败处理。
- `docs/service_checklist.md`：部署与提交前检查。
- `docs/SUBMISSION_18.md`、`docs/SUBMISSION_15.md`：可重新生成的提交说明。

```bash
.venv/bin/python scripts/gen_submission.py
.venv/bin/python scripts/gen_submission_15.py
```

## 仍需人工完成的材料

| 项目 | 当前状态 |
|---|---|
| 团队成员姓名与联系方式 | `需人工填写` |
| 公网服务地址与真实鉴权说明 | `https://devils.corvusapi.org`；当前公开访问，不要求 Bearer |
| 仓库提交地址及评审访问权限 | `需人工填写并确认` |
| 真实用户试用记录 | `待完成` |
| 小红书帖子 URL 与社区反馈 | `待完成` |
| 演示视频及链接 | `待完成` |
| Expo 专用幻灯片 | `待完成`；仓库现有 `docs/pitch/deck.html` 不能证明该材料已提交 |
| 封面图 | `待完成`；仓库中未发现可核验的封面图片文件 |

> 本内容由多智能体辩论生成，仅供学习与研究，不构成任何投资建议；不含买卖操作、目标价或收益承诺。历史或缓存数据不代表未来表现。
