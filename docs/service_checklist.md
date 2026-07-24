# 上线 / 稳定性 / 联调检查表（18 命脉）

> 18 最容易翻车的不是算法，是"评审期服务掉线 / 超 20 分钟 / 平台调不到"。这张表优先级最高。

## 部署（保证"评审期稳定在线"）
- [ ] 服务跑在**公网可达**的地址（Cloudflare Tunnel / 一台 VPS / 云容器），不是 localhost。
- [ ] `GET /healthz` 健康检查 + 进程守护（systemd / pm2 / docker restart:always）自动拉起。
- [ ] Agent Card 放 `/.well-known/agent-card.json`，**公网可访问**，URL 与 `agent-card.json` 里的 `url` 一致。
- [ ] 鉴权方式（bearer token）写清并在说明文档给出示例。
- [ ] 冗余：准备**第二个备份部署**，终审前一小时确认主备都在线。

## 时延（≤20 分钟硬上限）
- [ ] 全局预算 18 分钟（留 2 分钟余量）+ 每 Agent 超时（见 `orchestration.py`）。
- [ ] **streaming（SSE）**先吐进度事件，评委看得到"六个 Agent 在动"，消除等待焦虑。
- [ ] 7 天数据窗口内**预热缓存**：`DATA_MODE=panda python scripts/warm_cache.py <tickers…>`，
      落 `./.cache`；终审自动走缓存（`source=panda_cache`，命中时不碰 panda_data），窗口过期/限流也不崩。
- [ ] 设 `MAX_AUDIT_ROUNDS`，防止审计-重证死循环烧时间/烧 token。

## 平台联调（"可被平台成功调用"）
- [ ] 用飞书群发的**测试环境**验证 Agent 能被发现 + 调用（TODO(feishu)）。
- [ ] 对齐官方**示例 Agent Card** 字段（TODO(feishu)），别用猜的 schema。
- [ ] 跑通 **≥3 个示例任务**并存下输入/预期输出（提交清单要求）。
- [ ] 输出**可解释**：每条结论回链 skill 调用 + 数据，审计结果显式。
- [ ] 输出**过 compliance.py**：无买卖/收益承诺、带风险提示。

## 提交物（对照官方清单）
- [ ] Agent 名称、简介、团队信息
- [ ] Agent Card URL（公开可访问）
- [ ] 服务地址 + 鉴权方式
- [ ] 说明文档（使用场景、架构、Skills 调用方式、结果展示）
- [ ] 示例问题与预期输出（≥3）
- [ ] 用到的数据 Skills / 投研 Skills 列表
- [ ] GitHub 链接**或**邮件 code@pandaai.online
- [ ] 演示视频（完整核心流程）
- [ ] 输出含必要风险提示

## 终审前一键自检
- [ ] 对**公网 URL** 跑 `python scripts/smoke_a2a.py --url https://<你的公网地址>`（有鉴权加 `--token`）。
      13 项全绿（healthz / Agent Card / debate_case / audit_claims / SSE / 鉴权 / ≤20min / 溯源）= 可被评委调用。

## 红线（任一即失格）
- ✗ 评审期服务掉线
- ✗ 总响应 > 20 分钟
- ✗ 用未授权 / 实时数据
- ✗ 宣称收益 / 构成投资建议 / 荐股
- ✗ 多 Agent 只是串联、输出不可解释（判套壳）
