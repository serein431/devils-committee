# Repository Guidelines

## Project Structure & Module Organization

核心服务位于 `backend/`：`a2a_server.py` 提供 FastAPI、A2A 与 SSE 接口，`orchestration.py` 组织辩论流程，`agents.py`、`compliance.py` 和 `backend/skills/` 分别负责角色、输出检查与 QuantSkills 适配。静态前端集中在 `web/index.html`。自动化检查放在 `tests/`，示例数据位于 `tests/examples/`；运行、演示、上线检查和提交稿生成脚本放在 `scripts/`。架构、演示和参赛材料统一放在 `docs/`。修改公开能力时，同时检查根目录的 `agent-card.json`。

## Build, Test, and Development Commands

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest pytest-asyncio numpy
./run.sh
```

项目要求 Python 3.10 以上；示例使用 3.13，也可换成本机其他受支持版本。`run.sh` 会在 `http://localhost:8080` 启动服务。项目没有单独的前端构建步骤，FastAPI 直接提供 `web/index.html`。

```bash
.venv/bin/python -m pytest -q
./scripts/test_frontend.sh
.venv/bin/python scripts/smoke_a2a.py --url http://localhost:8080
```

三条命令分别运行后端测试、浏览器 DOM 测试和已启动服务的健康接口、Agent Card、A2A 与 SSE 检查。`test_frontend.sh` 会在首次运行时安装 `jsdom`。接入真实服务前，先复制 `.env.example` 为 `.env`，再运行 `.venv/bin/python scripts/setup_real.py --check`。

## Coding Style & Naming Conventions

Python 使用 4 空格缩进、类型注解和模块级说明；模块、函数与变量采用 `snake_case`，类采用 `PascalCase`，常量采用 `UPPER_SNAKE_CASE`。前端延续现有 2 空格缩进和原生 HTML/CSS/JavaScript 写法。仓库未配置统一格式化工具，提交前应保持相邻代码风格一致，并避免为小改动新增依赖。

## Testing Guidelines

Python 测试使用 `pytest`，文件命名为 `test_<主题>.py`，测试函数命名为 `test_<行为>()`。`tests/conftest.py` 会强制使用离线 mock 模式；新增功能应覆盖正常结果、失败处理和合规限制。前端行为写入 `tests/frontend.test.mjs`。当前没有强制覆盖率门槛，但后端与前端测试都必须通过。

## Commit & Pull Request Guidelines

当前副本不含 Git 历史，无法确认既有提交格式。建议使用简短、祈使式、带范围的消息，例如 `fix: sanitize A2A errors` 或 `test: cover thin-data audit`。Pull Request 应说明改动目的、受影响的运行模式、执行过的命令及结果；涉及 `web/index.html` 时附截图，涉及接口时附请求与响应示例，并关联相关 issue。

## Security & Configuration Tips

不要提交 `.env`、API 密钥、账号、缓存或真实用户数据。所有面向用户或 A2A 调用方的投资内容都必须经过 `backend/compliance.py`，错误响应不得泄露内部路径、凭证或异常详情。
