# Repository Guidelines

## Project Structure

`backend/` 保存 FastAPI、A2A、SSE、多 Agent 流程、合规检查和 QuantSkills 适配；`web/index.html` 是静态教练页面；`tests/` 放 Python、前端和三个 A 股示例；`scripts/` 放启动、真实环境检查、预计算、演示与提交稿生成脚本；`docs/` 放架构、演示和参评说明。修改公开接口时同时检查根目录 `agent-card.json`。

## Commands

默认开发使用 mock：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
.venv/bin/python -m pytest -q
./scripts/test_frontend.sh
```

真实环境必须使用 Python 3.12 和 `requirements-real.txt`：

```bash
python3.12 -m venv .venv-real
.venv-real/bin/pip install -r requirements-real.txt
git submodule update --init --recursive
.venv-real/bin/python scripts/setup_real.py --check
```

离线测试默认强制 mock。真实联调须明确设置 `RUN_LIVE_INTEGRATION=1`，并单独运行 `tests/test_live_integration.py`；不要让普通 CI 使用付费服务。

## Style and Naming

Python 使用 4 空格、类型注解和 `snake_case`；类名用 `PascalCase`，常量用 `UPPER_SNAKE_CASE`。前端保持现有 2 空格和原生 HTML、CSS、JavaScript。测试文件命名为 `test_<topic>.py`，测试函数命名为 `test_<behavior>()`。修改时保持相邻代码风格，不为小改动增加依赖。

## Runtime Facts

Volcengine Ark 的显示名称是 DeepSeek V4 Pro，`LLM_MODEL` 接收活动 Endpoint ID。真实研究只支持 A 股；其他市场返回 `insufficient-evidence`。每次真实请求运行四个在线 QuantSkills、一个项目内的指数权重变化研究，并读取 HPO 预计算结果；在线因子研究失败时可以读取可验证的预计算报告。来源必须区分 `live`、`cache`、`precomputed`、`mock`；缺少证据时使用 `insufficient-evidence`，真实失败不得改成 mock。

## Commits, PRs, and Security

提交消息保持简短，例如 `docs: describe verified integration`。PR 说明改动、影响的运行模式和执行过的检查；接口改动附脱敏请求示例，页面改动附截图。不要提交 `.env`、密钥、账号、缓存或真实用户数据。输出不得包含买卖指令、目标价、收益承诺或自动交易功能，并必须经过 `backend/compliance.py`。
