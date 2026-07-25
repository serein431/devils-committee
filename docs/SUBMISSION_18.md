# PandaAI（参评类别 18）提交说明 · Devil's Committee

> 本文件由 `scripts/gen_submission.py` 根据当前运行结果生成。默认环境使用 mock，
> 所以下面的示例只证明离线流程和返回结构可运行，不代表真实凭证、真实数据或公网部署已经完成。

## 1. Agent 名称、简介与团队
- **名称**：反方 · The Devil's Committee — AI 投资辩论庭
- **简介**：Bull、Bear、Macro、Risk 四个 Agent 使用同一批研究证据分别陈述，Audit Agent 独立检查论据，Chair 汇总共识、分歧和风险范围。
- **限制**：不给买卖指令、目标价、收益承诺，也不执行自动交易。仅供学习与研究。
- **团队成员与联系方式**：`需人工填写`。

## 2. A2A、Agent Card、SSE 与鉴权
- Agent Card：`GET /.well-known/agent-card.json`。公网地址：`需人工填写`。
- 调用入口：`POST /a2a`；请求头或查询参数可选择 SSE 流式返回。
- 鉴权：设置 `A2A_BEARER_TOKEN` 后使用 `Authorization: Bearer <token>`。
- 服务总请求限制为 600 秒；每个在线 Skill 和单个 Agent 的限制为 120 秒。
- 当前仓库能证明本地接口存在，不能证明评审期公网服务已经部署。

## 3. 模型、数据与市场范围
- LLM 通过 Volcengine Ark 调用，对外显示名称是 **DeepSeek V4 Pro**；`LLM_MODEL` 填活动提供的 Endpoint ID。
- 真实数据由 PandaData 提供，QuantSkills 读取研究所需的历史数据。
- 当前真实研究只支持 A 股。港股或其他境外市场请求返回 `insufficient-evidence`，不会改用 mock。
- 真实请求每次运行四个在线 QuantSkills，另外两个读取与当前构建和数据哈希相符的预计算报告。

## 4. 六个 Skill ID
**每次在线运行的四个：**
- `corporate-action-adjustment-auditor`
- `survivorship-universe-auditor`
- `portfolio-liquidity-stress-test`
- `index-rebalance-event-study`

**读取预计算结果的两个：**
- `factor-ranking-sage`
- `model-hpo-evidence-driven`

> 本地克隆目录和当前运行时 JSON 会在这些 ID 前加 `skill-`；提交材料使用上面的六个 ID。

## 5. 来源和状态怎么读
- `live`：本次从 PandaData 新取数据，并保存带 SHA-256 的内容哈希缓存。
- `cache`：读取此前保存且哈希校验通过的数据。
- `precomputed`：读取提交号、数据哈希和清单均可核验的因子或 HPO 报告。
- `mock`：离线开发用的固定模拟结果，不能当作公开研究证据。
- `insufficient-evidence`：缺少所需数据或报告，不能说成通过。真实来源失败时不会转成 mock。

## 6. 当前生成示例
```json
{
  "symbol": "600519.SH",
  "data_status": "success",
  "modes": [
    "mock"
  ],
  "n_claims": 4,
  "n_flags": 0,
  "skill_ids": [
    "corporate-action-adjustment-auditor",
    "survivorship-universe-auditor",
    "portfolio-liquidity-stress-test",
    "index-rebalance-event-study",
    "factor-ranking-sage",
    "model-hpo-evidence-driven"
  ],
  "audit_flags": [],
  "gives_investment_advice": false
}
```

## 7. 三个固定示例
- `600519.SH`：研究 600519.SH 的复权、分红、因子和流动性风险
- `300750.SZ`：研究 300750.SZ 的成长因子、波动、流动性和指数事件
- `601318.SH`：研究 601318.SH 的分红、股票池和风险证据

固定示例必须是 `600519.SH`、`300750.SZ`、`601318.SH`。真实结论取决于当次数据和可用证据，不预写审计结果。

## 8. 真实环境准备
```bash
python3.12 -m venv .venv-real
.venv-real/bin/pip install -r requirements-real.txt
git submodule update --init --recursive
.venv-real/bin/python scripts/setup_real.py --check
```
有效凭证只能放在本机 `.env` 或部署平台的私密配置中。

## 9. 仍需人工完成
- 团队姓名与联系方式：`需人工填写`。
- 公网服务地址与真实鉴权说明：`待完成`。
- 代码仓库提交地址及评审访问权限：`需人工填写并确认`。
- 演示视频及链接：`待完成`。
- 真实凭证环境下三个 A 股示例的脱敏记录：`待完成`。

## 10. 风险提示
> 本内容由多智能体辩论生成，仅供学习与研究，不构成任何投资建议；不含买卖操作、目标价或收益承诺。历史/缓存数据不代表未来表现。
