# 服务、联调与提交检查表

## 本地与真实环境

- [ ] 默认开发使用 mock，普通测试不访问付费服务。
- [ ] 真实环境使用 Python 3.12：

```bash
python3.12 -m venv .venv-real
.venv-real/bin/pip install -r requirements-real.txt
git submodule update --init --recursive
.venv-real/bin/python scripts/setup_real.py --check
```

- [ ] `.env` 中的 Volcengine Ark、PandaData 和 A2A 凭证只保存在私密配置中。
- [ ] Volcengine Ark 显示名称为 DeepSeek V4 Pro，`LLM_MODEL` 填活动 Endpoint ID。
- [ ] 真实研究仅使用 A 股。其他市场应返回 `insufficient-evidence`。

## 数据与 QuantSkills

- [ ] 三个固定示例为 `600519.SH`、`300750.SZ`、`601318.SH`。
- [ ] 每个真实请求运行四个在线 Skill：
  - `corporate-action-adjustment-auditor`
  - `survivorship-universe-auditor`
  - `portfolio-liquidity-stress-test`
  - `index-rebalance-event-study`
- [ ] 两个预计算 Skill 的清单、提交号和数据哈希均通过检查：
  - `factor-ranking-sage`
  - `model-hpo-evidence-driven`
- [ ] PandaData 缓存按请求内容生成键，Parquet 的 SHA-256 在读取时重新核验。
- [ ] 响应能区分 `live`、`cache`、`precomputed`、`mock` 和 `insufficient-evidence`。
- [ ] 真实数据、模型或 Skill 失败时返回错误或证据不足，不改成 mock。

## A2A 服务

- [x] `GET /healthz` 可访问。
- [x] `GET /.well-known/agent-card.json` 可访问，`supportedInterfaces` 指向当前 `/a2a`。
- [x] `SendMessage`、`GetTask` 和 `CancelTask` 使用 A2A v1 JSON-RPC 结构。
- [x] `SendStreamingMessage` 返回 Task、工作状态、结果 artifact 和终态。
- [ ] 设置 `A2A_BEARER_TOKEN` 后，无 Token 和错误 Token 均被拒绝。
- [ ] 整个请求限制为 600 秒，在线 Skill 和单个 Agent 限制为 120 秒。
- [ ] 对外文本经过 `backend/compliance.py`，没有买卖指令、目标价、收益承诺或自动交易描述。

## 公网与评审访问

- [x] 公网服务地址：`https://devils.corvusapi.org`。
- [x] systemd 进程守护、健康检查和 Caddy HTTPS：已实测。
- [x] 公网 Agent Card、A2A 普通调用和 SSE：已实测；当前公开访问，不要求 Bearer。
- [x] `scripts/smoke_a2a.py` 已更新为 A2A v1 的 17 项检查。
- [ ] 代码仓库提交地址：`需人工填写`。
- [ ] 评审账号或仓库访问权限：`需人工确认`。

## 人工提交材料

- [ ] 团队成员姓名、分工和联系方式：`需人工填写`。
- [ ] 真实用户试用人数、授权、原话和改动记录：`待完成`。
- [ ] 小红书已发布帖子 URL 与社区反馈：`待完成`。
- [ ] 演示视频及链接：`待完成`。
- [ ] 真实凭证环境下三个 A 股示例的脱敏记录：`待完成`。
- [ ] Expo 专用幻灯片：`待完成`；现有 `docs/pitch/deck.html` 不能证明该材料已经提交。
- [ ] 封面图：`待完成`；仓库中未发现可核验的封面图片文件。

完成状态只能根据可访问链接、实际运行结果或仓库文件修改，不能根据计划提前勾选。
