# 真实服务联调

这份说明只用于人工准备真实环境。普通测试仍使用离线模拟数据，不会调用付费模型或 PandaData。

## 准备顺序

在仓库根目录依次运行：

```bash
python3.12 -m venv .venv-real
.venv-real/bin/pip install -r requirements-real.txt
cp .env.example .env
git submodule update --init --recursive
.venv-real/bin/python scripts/setup_real.py --check
DATA_MODE=panda .venv-real/bin/python scripts/warm_cache.py
DATA_MODE=panda SKILL_MODE=cli .venv-real/bin/python scripts/precompute_research.py
RUN_LIVE_INTEGRATION=1 .venv-real/bin/python -m pytest tests/test_live_integration.py -v
```

复制 `.env.example` 后，人工把有效的 `LLM_API_KEY`、`LLM_MODEL`、`DEFAULT_USERNAME` 和 `DEFAULT_PASSWORD` 写入 `.env`。如 A2A 服务启用了鉴权，还需填写 `A2A_BEARER_TOKEN`。凭证只能留在本机 `.env`、密码管理器或部署环境的密钥配置中，不要把值写进文档、命令参数、终端历史、测试输出或 Git 提交。

`scripts/setup_real.py --check` 只报告项目是否齐全，不会探测公开接口，也不会打印凭证、HTTP 请求头、响应正文或本地路径。检查内容包括 Python 3.12、模型 endpoint ID、PandaData 账号和密码、七个 QuantSkills 仓库、两个预计算清单以及数值配置。

## 结果含义

- `live`：本次请求从 PandaData 取得了新数据。
- `cache`：本次请求读取了此前验证过的本地缓存。
- `precomputed`：因子筛选或 HPO 结果来自当前构建可验证的预计算文件。
- `insufficient-evidence`：真实来源缺少所需字段或记录，当前 Skill 不能给出完整结果。这不是通过，也不应改写成成功。

真实模式下如果 PandaData、模型或 QuantSkills 失败，程序会返回错误或证据不足，不会改用 `mock`。因此真实测试允许个别 Skill 为 `insufficient-evidence`，但不允许出现 `mock`；六个 Skill ID 必须全部存在。

## 缓存预热

推荐使用下列命令：

```bash
DATA_MODE=panda .venv-real/bin/python scripts/warm_cache.py
```

默认处理 `600519.SH`、`300750.SZ` 和 `601318.SH`。输出只包含标的、状态、数据集名称、行数、`live/cache` 模式和 SHA-256 前八位。任一标的缺少 `daily` 数据或返回非成功状态时，脚本继续处理剩余标的，最后以退出码 1 结束。

如果未设置 `DATA_MODE=panda`，输出会明确显示 `mock`。这只能用于检查脚本本身，不能作为真实联调结果。

## 保存脱敏记录

服务启动后，可对本机或公网地址运行：

```bash
.venv-real/bin/python scripts/record_live_examples.py --url https://example.com
```

脚本会读取进程环境中的 `A2A_BEARER_TOKEN`。不要使用 `--token` 直接跟真实值；这会让值进入终端历史和进程参数。需要鉴权时，应由密码管理器、部署服务或当前会话已有的私密环境变量提供。

三个请求的记录只写入 `var/live-records/<symbol>/`，每个目录含 `request.json`、`response.json`、`skills.json` 和 `README.md`。写入前会递归清除鉴权、Cookie、模型密钥、PandaData 账号和密码。`README.md` 只保存 UTC 时间、服务主机名、总耗时、数据模式和六个 Skill 状态，不保存 URL 路径、查询参数、请求头或凭证。

`var/live-records/` 已被 Git 忽略。不要强制加入这些真实记录，也不要把它们复制到参赛文档或公开 issue 中。
