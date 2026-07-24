# PandaAI Real Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有离线演示改成可验证的 A 股研究服务，真实调用火山方舟 DeepSeek V4 Pro、PandaData 和六个 QuantSkills，并在证据缺失时明确返回 `insufficient-evidence`。

**Architecture:** A2A 请求先转换为 `ResearchRequest`，再由 PandaData 适配器生成带文件哈希的 `MarketDataBundle`。四个在线 QuantSkills 读取同一数据包，两个提前计算的 QuantSkills 读取带提交号和数据哈希的报告；Agent 只解释这些 `SkillResult`，不再自行编造指标。真实服务失败时只使用参数和哈希均匹配的真实缓存，不改用模拟数据。

**Tech Stack:** Python 3.12、FastAPI、httpx、`panda_data==0.0.12`、Pandas、PyArrow、DuckDB、QuantSkills CLI、pytest、Node.js DOM tests。

---

## 文件安排

- `backend/research_request.py`：解析自然语言和 JSON 请求，规范 A 股代码，拒绝当前不支持的市场。
- `backend/skills/contracts.py`：定义 `DatasetArtifact`、`MarketDataBundle`、`SkillFinding`、`SkillResult`。
- `backend/skills/cache.py`：按方法、参数、SDK 版本和数据版本保存 Parquet 与 JSON 元数据，并校验 SHA-256。
- `backend/skills/panda.py`：登录 PandaData、调用已确认的方法、构建共享数据包。
- `backend/skills/online.py`：准备四个在线 Skill 的 CSV，按明确脚本名调用并统一结果。
- `backend/skills/precomputed.py`：读取因子排名和参数搜索报告，检查日期、提交号和数据哈希。
- `scripts/precompute_research.py`：生成特征与标签，并运行两个提前计算的 QuantSkills。
- `backend/skills/runner.py`：一次准备全部研究证据，供所有 Agent 共用。
- `backend/agents.py`：只引用 `SkillResult` 中已有的结论、假设和数据哈希。
- `backend/orchestration.py`：执行 10 分钟总限制、单个在线 Skill 120 秒限制和失败降级。
- `backend/a2a_server.py`：接收结构化研究参数并返回可检查的来源状态。
- `tests/`：默认测试完全离线；真实测试由 `RUN_LIVE_INTEGRATION=1` 单独开启。

### Task 1: 固定真实运行配置与依赖

**Files:**
- Modify: `backend/config.py`
- Modify: `.env.example`
- Modify: `requirements.txt`
- Create: `requirements-real.txt`
- Modify: `scripts/fetch_quantskills.sh`
- Modify: `scripts/setup_real.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写配置失败测试**

在 `tests/test_config.py` 增加：

```python
def test_official_live_defaults(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("JAVA_SERVICE_BASE_URL", raising=False)
    monkeypatch.delenv("SKILL_TIMEOUT_SEC", raising=False)
    monkeypatch.delenv("REQUEST_BUDGET_SEC", raising=False)
    cfg = config.Config()
    assert cfg.llm_provider == "volcengine-ark"
    assert cfg.llm_base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert cfg.llm_model_label == "DeepSeek V4 Pro"
    assert cfg.panda_base_url == "http://pandadata.pandaaiquant.com"
    assert cfg.skill_timeout_sec == 120
    assert cfg.request_budget_sec == 600


def test_summary_never_contains_credentials():
    cfg = config.Config(
        llm_api_key="secret-key",
        panda_username="private-user",
        panda_password="private-pass",
        bearer_token="private-token",
    )
    rendered = repr(cfg.summary())
    for secret in ("secret-key", "private-user", "private-pass", "private-token"):
        assert secret not in rendered
```

- [ ] **Step 2: 运行测试，确认当前配置不符合要求**

Run: `.venv/bin/python -m pytest tests/test_config.py::test_official_live_defaults tests/test_config.py::test_summary_never_contains_credentials -v`

Expected: FAIL，缺少 `llm_provider`、`llm_model_label`、`skill_timeout_sec` 或默认地址不正确。

- [ ] **Step 3: 改写配置字段，使用实例化时读取环境变量的默认值**

在 `backend/config.py` 使用以下字段；现有 `_load_dotenv()` 和 `_env()` 保留：

```python
from dataclasses import dataclass, field


def _str_field(key: str, default: str = ""):
    return field(default_factory=lambda: _env(key, default))


@dataclass(frozen=True)
class Config:
    llm_mode: str = _str_field("LLM_MODE", "mock")
    skill_mode: str = _str_field("SKILL_MODE", "mock")
    data_mode: str = _str_field("DATA_MODE", "mock")

    llm_provider: str = _str_field("LLM_PROVIDER", "volcengine-ark")
    llm_base_url: str = _str_field(
        "LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
    )
    llm_api_key: str = _str_field("LLM_API_KEY")
    llm_model: str = _str_field("LLM_MODEL")
    llm_model_label: str = _str_field("LLM_MODEL_LABEL", "DeepSeek V4 Pro")
    llm_temperature: float = field(
        default_factory=lambda: float(_env("LLM_TEMPERATURE", "0.2"))
    )

    panda_username: str = _str_field("DEFAULT_USERNAME")
    panda_password: str = _str_field("DEFAULT_PASSWORD")
    panda_base_url: str = _str_field(
        "JAVA_SERVICE_BASE_URL", "http://pandadata.pandaaiquant.com"
    )

    quantskills_dir: str = _str_field("QUANTSKILLS_DIR", "./vendor/quantskills")
    precomputed_dir: str = _str_field("PRECOMPUTED_DIR", "./var/precomputed")
    cache_dir: str = _str_field("CACHE_DIR", "./var/cache")
    data_version: str = _str_field("DATA_VERSION", "panda-2026-07")
    build_commit: str = _str_field("BUILD_COMMIT")
    skill_timeout_sec: int = field(
        default_factory=lambda: int(_env("SKILL_TIMEOUT_SEC", "120"))
    )
    request_budget_sec: int = field(
        default_factory=lambda: int(_env("REQUEST_BUDGET_SEC", "600"))
    )

    host: str = _str_field("HOST", "0.0.0.0")
    port: int = field(default_factory=lambda: int(_env("PORT", "8080")))
    public_url: str = _str_field("PUBLIC_URL", "http://localhost:8080")
    repository_url: str = _str_field(
        "REPOSITORY_URL", "https://github.com/serein431/devils-committee"
    )
    bearer_token: str = _str_field("A2A_BEARER_TOKEN")

    def summary(self) -> dict[str, str | int]:
        return {
            "llm_mode": self.llm_mode,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model_label if self.llm_mode != "mock" else "(mock)",
            "skill_mode": self.skill_mode,
            "data_mode": self.data_mode,
            "auth": "on" if self.bearer_token else "off (dev)",
            "public_url": self.public_url,
            "skill_timeout_sec": self.skill_timeout_sec,
            "request_budget_sec": self.request_budget_sec,
        }
```

- [ ] **Step 4: 固定真实依赖和七个仓库**

`requirements-real.txt` 写成：

```text
-r requirements.txt
numpy>=1.26,<2
pandas>=2.2,<3
pyarrow>=16,<20
duckdb>=1.1,<2
panda_data==0.0.12
scikit-learn>=1.5,<2
lightgbm>=4.5,<5
torch>=2.3,<3
PyYAML>=6,<7
```

`scripts/fetch_quantskills.sh` 的 `REPOS` 只保留：

```bash
REPOS=(
  skill-pandadata-api
  skill-corporate-action-adjustment-auditor
  skill-survivorship-universe-auditor
  skill-portfolio-liquidity-stress-test
  skill-index-rebalance-event-study
  skill-factor-ranking-sage
  skill-model-hpo-evidence-driven
)
```

`.env.example` 使用以下真实配置名，值保持为空的项目不得填写真实凭证：

```text
LLM_MODE=mock
LLM_PROVIDER=volcengine-ark
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_API_KEY=
LLM_MODEL=
LLM_MODEL_LABEL=DeepSeek V4 Pro
LLM_TEMPERATURE=0.2

DATA_MODE=mock
DEFAULT_USERNAME=
DEFAULT_PASSWORD=
JAVA_SERVICE_BASE_URL=http://pandadata.pandaaiquant.com

SKILL_MODE=mock
QUANTSKILLS_DIR=./vendor/quantskills
PRECOMPUTED_DIR=./var/precomputed
CACHE_DIR=./var/cache
DATA_VERSION=panda-2026-07
BUILD_COMMIT=
SKILL_TIMEOUT_SEC=120
REQUEST_BUDGET_SEC=600
```

同时让 `scripts/setup_real.py` 检查 Python 为 3.12、`LLM_MODEL` 非空、七个仓库齐全，并只打印“存在/缺失”和 HTTP 状态，不打印服务响应正文。

- [ ] **Step 5: 运行配置测试和脚本静态检查**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`

Expected: PASS。

Run: `bash -n scripts/fetch_quantskills.sh && .venv/bin/python scripts/setup_real.py`

Expected: shell 检查通过；准备报告不得显示任何凭证值。

- [ ] **Step 6: 提交**

```bash
git add backend/config.py .env.example requirements.txt requirements-real.txt scripts/fetch_quantskills.sh scripts/setup_real.py tests/test_config.py
git commit -m "build: pin PandaAI live runtime"
```

### Task 2: 建立研究请求和市场支持边界

**Files:**
- Create: `backend/research_request.py`
- Modify: `backend/orchestration.py`
- Test: `tests/test_research_request.py`
- Modify: `tests/test_orchestration.py`

- [ ] **Step 1: 写请求解析失败测试**

创建 `tests/test_research_request.py`：

```python
from backend.research_request import ResearchRequest, normalize_symbol


def test_normalizes_supported_a_share_symbols():
    assert normalize_symbol("600519") == ("600519.SH", "cn")
    assert normalize_symbol("sz300750") == ("300750.SZ", "cn")
    assert normalize_symbol("601318.SH") == ("601318.SH", "cn")


def test_marks_hk_and_us_as_unsupported():
    assert normalize_symbol("00700.HK") == ("00700.HK", "unsupported")
    assert normalize_symbol("NVDA") == ("NVDA", "unsupported")


def test_payload_fields_override_text_defaults():
    req = ResearchRequest.from_payload({
        "topic": "分析 600519",
        "symbol": "300750.SZ",
        "question": "流动性风险如何？",
        "start_date": "20240101",
        "end_date": "20260724",
        "portfolio_value": 500000.0,
        "spread_bps": 8.0,
    })
    assert req.symbol == "300750.SZ"
    assert req.question == "流动性风险如何？"
    assert req.portfolio_value == 500000.0
    assert req.spread_bps == 8.0
    assert req.supported is True


def test_unknown_text_does_not_become_a_fake_symbol():
    req = ResearchRequest.from_payload({"topic": "帮我看看这个东西"})
    assert req.symbol == "UNKNOWN"
    assert req.supported is False
```

- [ ] **Step 2: 运行测试，确认模块尚不存在**

Run: `.venv/bin/python -m pytest tests/test_research_request.py -v`

Expected: FAIL with `ModuleNotFoundError: backend.research_request`。

- [ ] **Step 3: 创建完整请求类型和代码解析函数**

创建 `backend/research_request.py`：

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


def normalize_symbol(value: str) -> tuple[str, str]:
    raw = value.strip().upper()
    a_share = re.fullmatch(r"(?:(SH|SZ))?(\d{6})(?:\.(SH|SZ))?", raw)
    if a_share:
        prefix, digits, suffix = a_share.groups()
        exchange = suffix or prefix or ("SH" if digits.startswith("6") else "SZ")
        return f"{digits}.{exchange}", "cn"
    if re.fullmatch(r"\d{5}\.HK", raw) or re.fullmatch(r"[A-Z]{1,5}", raw):
        return raw, "unsupported"
    return "UNKNOWN", "unknown"


def symbol_from_text(text: str) -> tuple[str, str]:
    match = re.search(r"(?i)(?<!\w)(?:(?:sh|sz)\d{6}|\d{6}(?:\.(?:sh|sz))?)(?!\w)", text)
    if match:
        return normalize_symbol(match.group(0))
    match = re.search(r"(?<!\w)(\d{5}\.HK|[A-Z]{1,5})(?!\w)", text)
    return normalize_symbol(match.group(1)) if match else ("UNKNOWN", "unknown")


@dataclass(frozen=True)
class ResearchRequest:
    symbol: str
    market: str
    question: str
    start_date: str
    end_date: str
    portfolio_value: float | None = None
    spread_bps: float | None = None

    @property
    def supported(self) -> bool:
        return self.market == "cn"

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ResearchRequest":
        topic = str(payload.get("topic") or payload.get("question") or "").strip()
        symbol, market = (
            normalize_symbol(str(payload["symbol"]))
            if payload.get("symbol")
            else symbol_from_text(topic)
        )
        end = str(payload.get("end_date") or date.today().strftime("%Y%m%d"))
        start = str(
            payload.get("start_date")
            or (date.today() - timedelta(days=730)).strftime("%Y%m%d")
        )
        return cls(
            symbol=symbol,
            market=market,
            question=str(payload.get("question") or topic).strip(),
            start_date=start,
            end_date=end,
            portfolio_value=(float(payload["portfolio_value"]) if payload.get("portfolio_value") is not None else None),
            spread_bps=(float(payload["spread_bps"]) if payload.get("spread_bps") is not None else None),
        )
```

把 `backend/orchestration.py` 的 `_extract_symbol()` 改为调用 `symbol_from_text(topic)[0]`，暂时保留原函数名，避免现有调用方立刻中断：

```python
from .research_request import symbol_from_text


def _extract_symbol(topic: str) -> str:
    return symbol_from_text(topic)[0]
```

- [ ] **Step 4: 更新旧测试并运行**

删除 `tests/test_orchestration.py` 中期望美股得到正常代码的断言，改为：

```python
def test_extract_symbol_keeps_a_share_support_boundary():
    assert _extract_symbol("贵州茅台 600519 多空") == "600519.SH"
    assert _extract_symbol("分析 sz300750") == "300750.SZ"
    assert _extract_symbol("分析 NVDA") == "NVDA"
    assert _extract_symbol("帮我看看这个东西") == "UNKNOWN"
```

Run: `.venv/bin/python -m pytest tests/test_research_request.py tests/test_orchestration.py -v`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/research_request.py backend/orchestration.py tests/test_research_request.py tests/test_orchestration.py
git commit -m "feat: define supported research requests"
```

### Task 3: 建立可校验的 PandaData 数据包和真实缓存

**Files:**
- Modify: `backend/skills/contracts.py`
- Rewrite: `backend/skills/cache.py`
- Create: `backend/skills/panda.py`
- Modify: `backend/skills/data.py`
- Test: `tests/test_skill_contracts.py`
- Rewrite: `tests/test_cache.py`
- Rewrite: `tests/test_panda_parse.py`

- [ ] **Step 1: 写数据契约、缓存和失败行为测试**

创建 `tests/test_skill_contracts.py`：

```python
from backend.skills.contracts import DatasetArtifact, MarketDataBundle, SkillFinding, SkillResult


def test_skill_result_serializes_traceable_evidence():
    result = SkillResult(
        skill_id="skill-corporate-action-adjustment-auditor",
        mode="live",
        status="success",
        duration_ms=42,
        dataset_hashes=["abc"],
        findings=[SkillFinding("复权记录可核对", ["daily", "adj_factor"], 0.9)],
    )
    payload = result.to_dict()
    assert payload["status"] == "success"
    assert payload["dataset_hashes"] == ["abc"]
    assert payload["findings"][0]["evidence_refs"] == ["daily", "adj_factor"]


def test_bundle_is_insufficient_when_required_daily_data_is_missing():
    bundle = MarketDataBundle.insufficient(
        symbol="600519.SH",
        reason="daily dataset unavailable",
    )
    assert bundle.status == "insufficient-evidence"
    assert bundle.datasets == {}
```

把 `tests/test_panda_parse.py` 中两个模拟回退测试替换为：

```python
from backend.research_request import ResearchRequest


def _request(symbol: str) -> ResearchRequest:
    return ResearchRequest(symbol, "cn", "数据检查", "20260716", "20260724")


def _panda_mode(monkeypatch, tmp_path, error=None):
    from backend.skills import cache, panda

    cfg = dataclasses.replace(
        CONFIG,
        data_mode="panda",
        cache_dir=str(tmp_path),
        panda_username="u",
        panda_password="p",
        panda_base_url="http://example.invalid",
    )
    monkeypatch.setattr(cache, "CONFIG", cfg)
    monkeypatch.setattr(panda, "CONFIG", cfg)
    if error is not None:
        module = types.ModuleType("panda_data")
        module.__version__ = "0.0.12"
        module.init_token = lambda **kwargs: None

        def raise_error(**kwargs):
            raise error

        module.get_stock_daily = raise_error
        monkeypatch.setitem(sys.modules, "panda_data", module)
    return panda


def _install_fake_panda(monkeypatch, daily_frame):
    module = types.ModuleType("panda_data")
    module.__version__ = "0.0.12"
    module.init_token = lambda **kwargs: None
    module.get_stock_daily = lambda **kwargs: daily_frame
    monkeypatch.setitem(sys.modules, "panda_data", module)


def test_empty_live_result_is_insufficient_not_mock(monkeypatch, tmp_path):
    panda = _panda_mode(monkeypatch, tmp_path)
    _install_fake_panda(monkeypatch, _FakeDF({"date": [], "close": []}))
    bundle = panda.build_market_data_bundle(_request("600519.SH"))
    assert bundle.status == "insufficient-evidence"
    assert bundle.mode != "mock"


def test_live_fetch_error_is_insufficient_not_mock(monkeypatch, tmp_path):
    panda = _panda_mode(monkeypatch, tmp_path, error=RuntimeError("network down"))
    bundle = panda.build_market_data_bundle(_request("600519.SH"))
    assert bundle.status == "insufficient-evidence"
    assert "RuntimeError" not in " ".join(bundle.warnings)
```

- [ ] **Step 2: 运行测试，确认当前真实模式仍会返回模拟行情**

Run: `.venv/bin/python -m pytest tests/test_skill_contracts.py tests/test_cache.py tests/test_panda_parse.py -v`

Expected: FAIL；现有 `get_stock_daily()` 在真实请求失败时返回 `source="mock"`。

- [ ] **Step 3: 增加统一数据和 Skill 类型**

在 `backend/skills/contracts.py` 保留当前离线辅助函数，并增加：

```python
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ResultStatus = Literal["success", "insufficient-evidence", "error"]
SourceMode = Literal["live", "cache", "precomputed", "mock"]


@dataclass(frozen=True)
class DatasetArtifact:
    name: str
    method: str
    params: dict[str, Any]
    path: str
    sha256: str
    rows: int
    mode: Literal["live", "cache", "mock"]
    fetched_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MarketDataBundle:
    symbol: str
    status: ResultStatus
    mode: Literal["live", "cache", "mock"]
    datasets: dict[str, DatasetArtifact] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def insufficient(cls, symbol: str, reason: str) -> "MarketDataBundle":
        return cls(symbol, "insufficient-evidence", "live", warnings=[reason])

    @property
    def dataset_hashes(self) -> list[str]:
        return sorted({item.sha256 for item in self.datasets.values()})


@dataclass(frozen=True)
class SkillFinding:
    claim: str
    evidence_refs: list[str]
    confidence: float


@dataclass
class SkillResult:
    skill_id: str
    mode: SourceMode
    status: ResultStatus
    duration_ms: int
    dataset_hashes: list[str]
    assumptions: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    findings: list[SkillFinding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

- [ ] **Step 4: 改为内容寻址缓存并校验文件哈希**

`backend/skills/cache.py` 提供下面的公开接口：

```python
def cache_key(method: str, params: dict, sdk_version: str, data_version: str) -> str:
    body = json.dumps(
        {"method": method, "params": params, "sdk_version": sdk_version, "data_version": data_version},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DatasetCache:
    def __init__(self, root: str, data_version: str) -> None:
        self.root = Path(root)
        self.data_version = data_version

    def load(self, name: str, method: str, params: dict, sdk_version: str) -> DatasetArtifact | None:
        key = cache_key(method, params, sdk_version, self.data_version)
        meta_path = self.root / name / f"{key}.json"
        data_path = self.root / name / f"{key}.parquet"
        if not meta_path.exists() or not data_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if file_sha256(data_path) != meta.get("sha256"):
            return None
        return DatasetArtifact(**{**meta, "path": str(data_path), "mode": "cache"})

    def save(self, name: str, method: str, params: dict, sdk_version: str, frame) -> DatasetArtifact:
        key = cache_key(method, params, sdk_version, self.data_version)
        target = self.root / name
        target.mkdir(parents=True, exist_ok=True)
        data_path = target / f"{key}.parquet"
        temp_path = target / f"{key}.parquet.tmp"
        frame.to_parquet(temp_path, index=False)
        temp_path.replace(data_path)
        artifact = DatasetArtifact(
            name=name,
            method=method,
            params=params,
            path=str(data_path),
            sha256=file_sha256(data_path),
            rows=len(frame),
            mode="live",
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
        meta_path = target / f"{key}.json"
        meta_path.write_text(json.dumps(artifact.to_dict(), ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return artifact
```

测试使用一个带 `to_parquet()` 的小型假对象写固定字节，不要求默认测试安装 Pandas 或 PyArrow。

- [ ] **Step 5: 创建 PandaData 适配器并禁止真实模式使用模拟结果**

`backend/skills/panda.py` 使用明确的方法和参数：

```python
DATASET_CALLS = {
    "daily": ("get_stock_daily", lambda r: {"symbol": [r.symbol], "start_date": r.start_date, "end_date": r.end_date, "fields": [], "indicator": "000300", "st": True}),
    "daily_pre": ("get_stock_daily_pre", lambda r: {"symbol": [r.symbol], "start_date": r.start_date, "end_date": r.end_date, "fields": [], "indicator": "000300", "st": True}),
    "daily_post": ("get_stock_daily_post", lambda r: {"symbol": [r.symbol], "start_date": r.start_date, "end_date": r.end_date, "fields": [], "indicator": "000300", "st": True}),
    "adj_factor": ("get_adj_factor", lambda r: {"symbol": r.symbol, "start_date": r.start_date, "end_date": r.end_date, "fields": []}),
    "dividend": ("get_stock_dividend", lambda r: {"symbol": r.symbol, "start_date": r.start_date, "end_date": r.end_date}),
    "status_change": ("get_stock_status_change", lambda r: {"symbol": r.symbol, "start_date": r.start_date, "end_date": r.end_date, "fields": []}),
    "trade_list_start": ("get_trade_list", lambda r: {"date": r.start_date, "exchange": r.symbol[-2:]}),
    "trade_list_end": ("get_trade_list", lambda r: {"date": r.end_date, "exchange": r.symbol[-2:]}),
    "index_weights": ("get_index_weights", lambda r: {"index_symbol": "000300.SH", "stock_symbol": r.symbol, "start_date": r.start_date, "end_date": r.end_date, "fields": []}),
    "index_daily": ("get_index_daily", lambda r: {"symbol": ["000300.SH"], "start_date": r.start_date, "end_date": r.end_date, "fields": []}),
    "factor": ("get_factor", lambda r: {"symbol": r.symbol, "start_date": r.start_date, "end_date": r.end_date, "factors": ["open", "close", "volume", "amount", "market_cap", "turnover"], "index_component": "000300", "type": "stock"}),
}
```

同一文件增加规范化和 mock 数据包函数：

```python
SENSITIVE_COLUMN_PARTS = {"authorization", "token", "password", "secret", "cookie"}


def normalize_frame(frame):
    clean = frame.copy()
    clean.columns = [str(column).strip() for column in clean.columns]
    lowered = {column.lower() for column in clean.columns}
    if any(part in column for column in lowered for part in SENSITIVE_COLUMN_PARTS):
        raise ValueError("sensitive column rejected")
    for column in clean.columns:
        if column == "date" or column.endswith("_date"):
            clean[column] = clean[column].map(
                lambda value: "" if value is None else str(value).replace("-", "").split(".")[0]
            )
    order = [column for column in ("date", "symbol", "stock_symbol", "index_symbol") if column in clean.columns]
    if order:
        clean = clean.sort_values(order)
    return clean.drop_duplicates().reset_index(drop=True)


def build_mock_bundle(request: ResearchRequest) -> MarketDataBundle:
    from .data import _mock_bars

    bars = _mock_bars(request.symbol)
    payload = json.dumps(
        {"symbol": bars.symbol, "dates": bars.dates, "close": bars.close, "volume": bars.volume},
        sort_keys=True,
        separators=(",", ":"),
    )
    artifact = DatasetArtifact(
        name="daily",
        method="mock_daily",
        params={"symbol": request.symbol},
        path=f"memory://mock/{request.symbol}",
        sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        rows=bars.n,
        mode="mock",
        fetched_at="deterministic",
    )
    return MarketDataBundle(request.symbol, "success", "mock", {"daily": artifact})
```

核心构建函数必须遵守以下分支：

```python
def build_market_data_bundle(request: ResearchRequest) -> MarketDataBundle:
    if not request.supported:
        return MarketDataBundle.insufficient(request.symbol, "current live research supports A shares only")
    if CONFIG.data_mode == "mock":
        return build_mock_bundle(request)

    cache = DatasetCache(CONFIG.cache_dir, CONFIG.data_version)
    try:
        import panda_data
        panda_data.init_token(
            username=CONFIG.panda_username,
            password=CONFIG.panda_password,
            base_url=CONFIG.panda_base_url,
        )
        sdk_version = getattr(panda_data, "__version__", "0.0.12")
    except Exception:
        return MarketDataBundle.insufficient(request.symbol, "PandaData authentication unavailable")

    datasets: dict[str, DatasetArtifact] = {}
    warnings: list[str] = []
    for name, (method_name, params_factory) in DATASET_CALLS.items():
        params = params_factory(request)
        cached = cache.load(name, method_name, params, sdk_version)
        if cached:
            datasets[name] = cached
            continue
        try:
            frame = getattr(panda_data, method_name)(**params)
            if frame is None or len(frame) == 0:
                warnings.append(f"{name} returned no rows")
                continue
            datasets[name] = cache.save(name, method_name, params, sdk_version, normalize_frame(frame))
        except Exception:
            warnings.append(f"{name} request failed")

    if "daily" not in datasets:
        return MarketDataBundle.insufficient(request.symbol, "daily dataset unavailable")
    mode = "live" if any(item.mode == "live" for item in datasets.values()) else "cache"
    return MarketDataBundle(request.symbol, "success", mode, datasets, warnings)
```

`normalize_frame()` 必须统一日期为八位字符串、按日期和代码升序、删除完全重复行，并拒绝包含访问令牌、密码、Authorization 字段的列名。

`backend/skills/data.py` 的 `get_stock_daily()` 在 `DATA_MODE=panda` 时改为读取新数据包；如果数据包不足，抛出公开的 `EvidenceUnavailable`，不得调用 `_mock_bars()`。

- [ ] **Step 6: 运行数据测试**

Run: `.venv/bin/python -m pytest tests/test_skill_contracts.py tests/test_cache.py tests/test_panda_parse.py -v`

Expected: PASS；真实错误测试的结果为 `insufficient-evidence`，缓存哈希不符时返回未命中。

- [ ] **Step 7: 提交**

```bash
git add backend/skills/contracts.py backend/skills/cache.py backend/skills/panda.py backend/skills/data.py tests/test_skill_contracts.py tests/test_cache.py tests/test_panda_parse.py
git commit -m "feat: build traceable PandaData bundles"
```

### Task 4: 接入四个在线 QuantSkills

**Files:**
- Modify: `backend/skills/cli.py`
- Create: `backend/skills/online.py`
- Modify: `backend/skills/runner.py`
- Test: `tests/test_cli_skill.py`
- Create: `tests/test_online_skills.py`

- [ ] **Step 1: 写明确入口、超时和结果统一测试**

在 `tests/test_cli_skill.py` 把调用方式改为明确脚本名：

```python
def test_real_survivorship_demo_runs_and_reports():
    real = cli.invoke(SKILL_DIR, "audit_universe.py", ["--demo"], timeout=120)
    assert real["status"] in ("pass", "fail", "warning", "insufficient-evidence")
    assert isinstance(real.get("findings"), list)


def test_missing_entry_is_rejected_without_guessing(tmp_path):
    (tmp_path / "scripts").mkdir()
    with pytest.raises(RuntimeError, match="skill entry unavailable"):
        cli.invoke(str(tmp_path), "audit_universe.py", ["--demo"], timeout=120)
```

创建 `tests/test_online_skills.py`：

```python
import asyncio

from backend.research_request import ResearchRequest
from backend.skills.contracts import DatasetArtifact, MarketDataBundle, SkillFinding, SkillResult
from backend.skills.online import OnlineSkillRunner, liquidity_parameters, report_to_result


def _artifact(name: str) -> DatasetArtifact:
    return DatasetArtifact(
        name=name,
        method=name,
        params={},
        path=f"/tmp/{name}.parquet",
        sha256=f"hash-{name}",
        rows=10,
        mode="cache",
        fetched_at="2026-07-24T00:00:00+00:00",
    )


def _request() -> ResearchRequest:
    return ResearchRequest("600519.SH", "cn", "分析风险", "20240101", "20260724")


def _bundle() -> MarketDataBundle:
    names = (
        "daily", "daily_post", "adj_factor", "dividend", "status_change",
        "trade_list_start", "trade_list_end", "index_weights", "index_daily",
    )
    return MarketDataBundle(
        "600519.SH",
        "success",
        "cache",
        {name: _artifact(name) for name in names},
    )


def _success(skill_id: str, bundle: MarketDataBundle) -> SkillResult:
    return SkillResult(
        skill_id=skill_id,
        mode="cache",
        status="success",
        duration_ms=1,
        dataset_hashes=bundle.dataset_hashes,
        findings=[SkillFinding("checked", ["daily"], 0.8)],
    )


def test_all_four_online_skills_return_one_result(monkeypatch):
    bundle = _bundle()
    runner = OnlineSkillRunner()
    monkeypatch.setattr(runner, "run_adjustments", lambda request, bundle: _success("skill-corporate-action-adjustment-auditor", bundle))
    monkeypatch.setattr(runner, "run_survivorship", lambda request, bundle: _success("skill-survivorship-universe-auditor", bundle))
    monkeypatch.setattr(runner, "run_liquidity", lambda request, bundle: _success("skill-portfolio-liquidity-stress-test", bundle))
    monkeypatch.setattr(runner, "run_index_event", lambda request, bundle: _success("skill-index-rebalance-event-study", bundle))
    results = asyncio.run(runner.run_all(_request(), bundle))
    assert {item.skill_id for item in results} == {
        "skill-corporate-action-adjustment-auditor",
        "skill-survivorship-universe-auditor",
        "skill-portfolio-liquidity-stress-test",
        "skill-index-rebalance-event-study",
    }
    assert all(item.dataset_hashes for item in results)


def test_timeout_only_marks_the_slow_skill(monkeypatch):
    import time

    runner = OnlineSkillRunner(timeout_sec=0.01)
    def slow(request, bundle):
        time.sleep(0.05)
        return _success("skill-corporate-action-adjustment-auditor", bundle)

    monkeypatch.setattr(runner, "run_adjustments", slow)
    monkeypatch.setattr(runner, "run_survivorship", lambda request, bundle: _success("skill-survivorship-universe-auditor", bundle))
    monkeypatch.setattr(runner, "run_liquidity", lambda request, bundle: _success("skill-portfolio-liquidity-stress-test", bundle))
    monkeypatch.setattr(runner, "run_index_event", lambda request, bundle: _success("skill-index-rebalance-event-study", bundle))
    results = asyncio.run(runner.run_all(_request(), _bundle()))
    assert sum(item.status == "error" for item in results) == 1
    assert sum(item.status == "success" for item in results) == 3


def test_missing_delisting_return_never_becomes_success():
    result = report_to_result(
        "skill-survivorship-universe-auditor",
        {"status": "pass", "findings": []},
        "cache",
        1,
        ["hash-trade-list"],
        forced_warning="delisting_return unavailable",
    )
    assert result.status == "insufficient-evidence"
    assert "delisting_return" in " ".join(result.warnings)


def test_liquidity_defaults_are_labeled_as_assumptions():
    params, assumptions = liquidity_parameters(_request(), avg_amount=20_000_000.0)
    assert params["position_value"] == 100000.0
    assert params["spread_bps"] == 10.0
    assert any("position_value" in item for item in assumptions)
    assert any("spread_bps" in item for item in assumptions)
```

- [ ] **Step 2: 运行测试，确认当前适配器会猜脚本且只接了两个审计器**

Run: `.venv/bin/python -m pytest tests/test_cli_skill.py tests/test_online_skills.py -v`

Expected: FAIL；`cli.invoke()` 没有 `entry` 参数，`OnlineSkillRunner` 尚不存在。

- [ ] **Step 3: 改写 CLI 调用，固定 120 秒上限**

`backend/skills/cli.py` 的公开函数改为：

```python
def invoke(
    skill_dir: str,
    entry: str,
    args: list[str],
    timeout: int = 120,
) -> dict[str, Any]:
    script = os.path.join(os.path.abspath(skill_dir), "scripts", entry)
    if not os.path.isfile(script):
        raise RuntimeError("skill entry unavailable")
    out_path = args[args.index("--out") + 1] if "--out" in args else None
    try:
        proc = subprocess.run(
            [sys.executable, script, *args],
            cwd=os.path.abspath(skill_dir),
            capture_output=True,
            text=True,
            timeout=min(timeout, 120),
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("skill execution timed out") from exc
    if proc.returncode != 0:
        raise RuntimeError("skill command failed")
    raw = Path(out_path).read_text(encoding="utf-8") if out_path else proc.stdout
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("skill returned invalid JSON") from exc
```

- [ ] **Step 4: 创建四个输入构建器和统一结果转换**

`backend/skills/online.py` 固定以下入口：

```python
ONLINE_SKILLS = {
    "skill-corporate-action-adjustment-auditor": (
        "audit_adjustments.py",
        ["--return-tolerance", "0.02", "--jump-threshold", "0.21"],
    ),
    "skill-survivorship-universe-auditor": ("audit_universe.py", []),
    "skill-portfolio-liquidity-stress-test": (
        "stress_liquidity.py",
        ["--participation", "0.1", "--volume-shock", "0.5", "--horizon-days", "5", "--eta", "0.5"],
    ),
    "skill-index-rebalance-event-study": (
        "study_index_rebalance.py",
        ["--start", "-5", "--end", "5"],
    ),
}
```

四个 CSV 必须使用官方脚本要求的列：

```python
ADJUSTMENT_COLUMNS = ["symbol", "date", "close", "adj_close", "split_factor", "cash_dividend"]
UNIVERSE_COLUMNS = ["symbol", "date", "listed_at", "delisted_at", "return", "delisting_return", "eligible"]
LIQUIDITY_COLUMNS = ["symbol", "position_value", "adv", "spread_bps", "volatility"]
EVENT_COLUMNS = [
    "event_id", "symbol", "action", "announcement_date", "effective_date",
    "relative_day", "return", "benchmark_return", "volume_ratio",
    "weight_before", "weight_after",
]
```

统一结果转换使用以下规则；`fail` 和 `warning` 代表 Skill 正常完成并找到了问题，因此仍是 `success`，问题写入 `findings`：

```python
def report_to_result(
    skill_id: str,
    report: dict,
    mode: str,
    duration_ms: int,
    dataset_hashes: list[str],
    assumptions: list[str] | None = None,
    forced_warning: str = "",
) -> SkillResult:
    raw_status = report.get("status")
    if raw_status == "insufficient-evidence" or forced_warning:
        status = "insufficient-evidence"
    elif raw_status in {"pass", "fail", "warning"}:
        status = "success"
    else:
        status = "error"
    findings = []
    for item in report.get("findings", []) or []:
        evidence = item.get("evidence", {}) if isinstance(item, dict) else {}
        claim = item.get("impact") or ", ".join(evidence.get("reasons", [])) or "QuantSkills finding"
        refs = [str(value) for value in evidence.values() if isinstance(value, str) and value]
        findings.append(SkillFinding(str(claim), refs[:5], 0.8))
    warnings = list(report.get("limitations", []) or [])
    if forced_warning:
        warnings.append(forced_warning)
    return SkillResult(
        skill_id=skill_id,
        mode=mode,
        status=status,
        duration_ms=duration_ms,
        dataset_hashes=sorted(set(dataset_hashes)),
        assumptions=list(assumptions or []),
        metrics=dict(report.get("metrics") or report.get("input_summary") or {}),
        findings=findings,
        warnings=[str(item) for item in warnings],
    )
```

流动性参数函数使用以下实现：

```python
def liquidity_parameters(
    request: ResearchRequest,
    avg_amount: float,
) -> tuple[dict[str, float], list[str]]:
    assumptions = []
    position_value = request.portfolio_value
    if position_value is None:
        position_value = 100000.0
        assumptions.append("position_value=100000 CNY demo assumption")
    spread_bps = request.spread_bps
    if spread_bps is None:
        spread_bps = 10.0
        assumptions.append("spread_bps=10 demo assumption")
    return {
        "position_value": float(position_value),
        "adv": float(avg_amount),
        "spread_bps": float(spread_bps),
    }, assumptions
```

错误结果使用固定公开文字：

```python
def error_result(skill_id: str, bundle: MarketDataBundle, warning: str) -> SkillResult:
    return SkillResult(
        skill_id=skill_id,
        mode=bundle.mode,
        status="error",
        duration_ms=0,
        dataset_hashes=bundle.dataset_hashes,
        warnings=[warning],
    )
```

输入准备规则必须写进代码并由测试覆盖：

- 公司行为：从 `daily` 和 `daily_post` 合并收盘价，从 `adj_factor` 取复权因子。PandaData 分红接口没有现金金额时，CSV 使用 `0` 只是满足脚本格式，结果强制为 `insufficient-evidence` 并说明 `cash_dividend amount unavailable`，不得把脚本的 `pass` 原样发布。
- 股票池：用起止日期的 `trade_list` 和 `status_change` 生成时点记录。没有标准化 `delisting_return` 时强制为 `insufficient-evidence`。
- 流动性：`adv` 使用真实成交额均值，`volatility` 使用日收益年化波动。请求没有 `portfolio_value` 或 `spread_bps` 时分别采用 `100000` 元和 `10` bps，并写入 `assumptions`。
- 指数事件：从 `index_weights` 找成分变化，以生效日为 0 日，合并股票和沪深 300 日收益。权重接口没有公告日时把 `announcement_date` 留空，并在结果中说明时间信息不完整。

- [ ] **Step 5: 并发执行四个 Skill，单个失败不影响其他结果**

`OnlineSkillRunner` 固定保存超时值；`run_adjustments()`、`run_survivorship()`、`run_liquidity()`、`run_index_event()` 分别按本任务前述列名生成临时 CSV，调用对应明确入口，再调用 `report_to_result()`：

```python
class OnlineSkillRunner:
    def __init__(self, timeout_sec: float = 120) -> None:
        self.timeout_sec = min(float(timeout_sec), 120.0)

    def _invoke(
        self,
        skill_id: str,
        entry: str,
        rows: list[dict],
        columns: list[str],
        extra_args: list[str],
    ) -> tuple[dict, int]:
        skill_dir = os.path.join(CONFIG.quantskills_dir, skill_id)
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "input.csv")
            output_path = os.path.join(temp_dir, "output.json")
            with open(input_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
            report = cli.invoke(
                skill_dir,
                entry,
                ["--input", input_path, "--out", output_path, *extra_args],
                timeout=int(self.timeout_sec),
            )
        return report, round((time.monotonic() - started) * 1000)
```

`run_all()` 使用独立线程包装同步 CLI：

```python
async def run_all(self, request: ResearchRequest, bundle: MarketDataBundle) -> list[SkillResult]:
    calls = [
        ("skill-corporate-action-adjustment-auditor", self.run_adjustments),
        ("skill-survivorship-universe-auditor", self.run_survivorship),
        ("skill-portfolio-liquidity-stress-test", self.run_liquidity),
        ("skill-index-rebalance-event-study", self.run_index_event),
    ]

    async def one(skill_id, call):
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(call, request, bundle),
                timeout=self.timeout_sec,
            )
        except asyncio.TimeoutError:
            return error_result(skill_id, bundle, "skill timed out")
        except Exception:
            return error_result(skill_id, bundle, "skill execution failed")

    return list(await asyncio.gather(*(one(skill_id, call) for skill_id, call in calls)))
```

使用 `(skill_id, callable)` 元组，不能依赖函数名推断仓库名。

- [ ] **Step 6: 把 `SkillRunner` 改为一次准备共享结果**

在 `backend/skills/runner.py` 增加：

```python
@dataclass
class ResearchEvidence:
    request: ResearchRequest
    bundle: MarketDataBundle
    results: dict[str, SkillResult]


class SkillRunner:
    async def prepare(self, request: ResearchRequest) -> ResearchEvidence:
        bundle = await asyncio.to_thread(build_market_data_bundle, request)
        if bundle.status != "success":
            return ResearchEvidence(request, bundle, {})
        online = await OnlineSkillRunner(CONFIG.skill_timeout_sec).run_all(request, bundle)
        return ResearchEvidence(request, bundle, {item.skill_id: item for item in online})
```

暂时保留现有 mock 辅助方法，下一任务加入两个提前计算结果后，再在 Agent 改写任务中删除未使用接口。

- [ ] **Step 7: 运行在线适配测试**

Run: `.venv/bin/python -m pytest tests/test_cli_skill.py tests/test_online_skills.py -v`

Expected: PASS；四个结果都有 `skill_id` 和数据哈希，超时测试只有一个 `error`。

- [ ] **Step 8: 提交**

```bash
git add backend/skills/cli.py backend/skills/online.py backend/skills/runner.py tests/test_cli_skill.py tests/test_online_skills.py
git commit -m "feat: run four verified QuantSkills"
```

### Task 5: 接入两个提前计算的 QuantSkills

**Files:**
- Create: `backend/skills/precomputed.py`
- Create: `scripts/precompute_research.py`
- Modify: `backend/skills/runner.py`
- Modify: `.gitignore`
- Create: `tests/test_precomputed_skills.py`

- [ ] **Step 1: 写报告有效期、提交号和哈希测试**

创建 `tests/test_precomputed_skills.py`：

```python
import hashlib
import json

from backend.skills.precomputed import PrecomputedStore


def _write_run(root, skill_id, manifest):
    inputs = root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    source = inputs / "features.csv"
    source.write_text("date,symbol,x\n20260724,600519.SH,1\n", encoding="utf-8")
    manifest = {
        **manifest,
        "universe": ["600519.SH", "300750.SZ", "601318.SH"],
        "source_files": {
            "inputs/features.csv": hashlib.sha256(source.read_bytes()).hexdigest()
        },
    }
    run = root / skill_id
    run.mkdir(parents=True)
    (run / "devils-committee-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    payload = {
        "selected_factors": ["momentum_20d", "turnover"],
        "metrics": {
            "n_obs": 600,
            "train_start": "20240101",
            "train_end": "20250131",
            "valid_start": "20250210",
            "valid_end": "20251231"
        },
        "warnings": []
    }
    (run / "result.json").write_text(json.dumps(payload), encoding="utf-8")


def test_matching_report_loads_as_precomputed(tmp_path):
    _write_run(tmp_path, "skill-factor-ranking-sage", {
        "generated_at": "2026-07-24T00:00:00+00:00",
        "git_commit": "abc123",
        "dataset_hashes": ["daily-hash", "factor-hash"],
        "result_file": "result.json",
    })
    result = PrecomputedStore(str(tmp_path), "abc123").load(
        "skill-factor-ranking-sage", "600519.SH"
    )
    assert result.status == "success"
    assert result.mode == "precomputed"


def test_hash_mismatch_is_insufficient(tmp_path):
    _write_run(tmp_path, "skill-factor-ranking-sage", {
        "generated_at": "2026-07-24T00:00:00+00:00",
        "git_commit": "abc123",
        "dataset_hashes": ["old-hash"],
        "result_file": "result.json",
    })
    (tmp_path / "inputs" / "features.csv").write_text("changed", encoding="utf-8")
    result = PrecomputedStore(str(tmp_path), "abc123").load(
        "skill-factor-ranking-sage", "600519.SH"
    )
    assert result.status == "insufficient-evidence"


def test_commit_mismatch_is_insufficient(tmp_path):
    _write_run(tmp_path, "skill-model-hpo-evidence-driven", {
        "generated_at": "2026-07-24T00:00:00+00:00",
        "git_commit": "old",
        "dataset_hashes": ["h"],
        "result_file": "result.json",
    })
    result = PrecomputedStore(str(tmp_path), "new").load(
        "skill-model-hpo-evidence-driven", "600519.SH"
    )
    assert result.status == "insufficient-evidence"
```

- [ ] **Step 2: 运行测试，确认读取器尚不存在**

Run: `.venv/bin/python -m pytest tests/test_precomputed_skills.py -v`

Expected: FAIL with `ModuleNotFoundError: backend.skills.precomputed`。

- [ ] **Step 3: 创建严格的提前计算报告读取器**

`backend/skills/precomputed.py` 的公开实现：

```python
from .cache import file_sha256


def insufficient_result(skill_id: str, warning: str) -> SkillResult:
    return SkillResult(
        skill_id=skill_id,
        mode="precomputed",
        status="insufficient-evidence",
        duration_ms=0,
        dataset_hashes=[],
        warnings=[warning],
    )


def parse_precomputed_findings(skill_id: str, payload: dict) -> list[SkillFinding]:
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("metrics missing")
    if skill_id == "skill-factor-ranking-sage":
        selected = payload.get("selected_factors")
        required = {"n_obs", "train_start", "train_end", "valid_start", "valid_end"}
        if not isinstance(selected, list) or not selected or not required <= set(metrics):
            raise ValueError("factor evidence incomplete")
        return [SkillFinding(
            claim=f"selected factors: {', '.join(map(str, selected))}",
            evidence_refs=["selected_factors.json", "run_manifest.json", "input_manifest.json"],
            confidence=0.85,
        )]
    if skill_id == "skill-model-hpo-evidence-driven":
        best_params = payload.get("best_params")
        required = {"successful_trials", "failed_trials", "seed", "validation_score"}
        if not isinstance(best_params, dict) or not best_params or not required <= set(metrics):
            raise ValueError("HPO evidence incomplete")
        return [SkillFinding(
            claim=f"validated parameter set with score {metrics['validation_score']}",
            evidence_refs=["best_params.json", "search_manifest.json", "trials.jsonl"],
            confidence=0.8,
        )]
    raise ValueError("unsupported precomputed skill")


class PrecomputedStore:
    def __init__(self, root: str, build_commit: str) -> None:
        self.root = Path(root)
        self.build_commit = build_commit

    def load(self, skill_id: str, symbol: str) -> SkillResult:
        run_dir = self.root / skill_id
        manifest_path = run_dir / "devils-committee-manifest.json"
        if not manifest_path.exists():
            return insufficient_result(skill_id, "precomputed manifest unavailable")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            result_path = run_dir / manifest["result_file"]
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, KeyError, ValueError):
            return insufficient_result(skill_id, "precomputed report unreadable")
        if self.build_commit and manifest.get("git_commit") != self.build_commit:
            return insufficient_result(skill_id, "precomputed report commit mismatch")
        if symbol not in manifest.get("universe", []):
            return insufficient_result(skill_id, "symbol absent from precomputed universe")
        for relative_path, expected_hash in manifest.get("source_files", {}).items():
            source_path = self.root / relative_path
            if not source_path.is_file() or file_sha256(source_path) != expected_hash:
                return insufficient_result(skill_id, "precomputed report dataset mismatch")
        try:
            findings = parse_precomputed_findings(skill_id, payload)
        except ValueError:
            return insufficient_result(skill_id, "precomputed evidence incomplete")
        return SkillResult(
            skill_id=skill_id,
            mode="precomputed",
            status="success",
            duration_ms=0,
            dataset_hashes=sorted(manifest.get("dataset_hashes", [])),
            metrics=dict(payload["metrics"]),
            findings=findings,
            warnings=[str(item) for item in payload.get("warnings", [])],
        )
```

缺少规定字段时返回 `insufficient-evidence`，不能填默认成功值。

- [ ] **Step 4: 创建可重复运行的提前计算脚本**

`scripts/precompute_research.py` 依次完成：

```python
FACTOR_SKILL = "skill-factor-ranking-sage"
HPO_SKILL = "skill-model-hpo-evidence-driven"
DEFAULT_UNIVERSE = [
    "600519.SH", "300750.SZ", "601318.SH", "000001.SZ", "600036.SH",
    "000858.SZ", "002594.SZ", "600030.SH", "600900.SH", "601166.SH",
]


def build_factor_tables(
    request: ResearchRequest,
    symbols: list[str],
) -> tuple[str, str, list[str]]:
    import pandas as pd

    frames = []
    hashes: set[str] = set()
    for symbol in symbols:
        item_request = dataclasses.replace(request, symbol=symbol)
        bundle = build_market_data_bundle(item_request)
        if bundle.status != "success" or not {"factor", "daily_post"} <= set(bundle.datasets):
            continue
        factor = pd.read_parquet(bundle.datasets["factor"].path)
        prices = pd.read_parquet(bundle.datasets["daily_post"].path)[["date", "symbol", "close"]]
        prices = prices.sort_values(["symbol", "date"])
        prices["y"] = prices.groupby("symbol")["close"].shift(-5) / prices["close"] - 1.0
        frames.append(factor.merge(prices[["date", "symbol", "y"]], on=["date", "symbol"], how="inner"))
        hashes.update(bundle.dataset_hashes)
    if not frames:
        raise RuntimeError("no factor rows available")
    combined = pd.concat(frames, ignore_index=True).dropna(subset=["y"])
    output = Path(CONFIG.precomputed_dir) / "inputs"
    output.mkdir(parents=True, exist_ok=True)
    feature_cols = [column for column in combined.columns if column not in {"y", "name"}]
    feature_path = output / "features.csv"
    label_path = output / "labels.csv"
    combined[feature_cols].to_csv(feature_path, index=False)
    combined[["date", "symbol", "y"]].to_csv(label_path, index=False)
    return str(feature_path), str(label_path), sorted(hashes)


def write_json_file(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def write_factor_config(feature_path: str, label_path: str) -> str:
    root = Path(CONFIG.precomputed_dir)
    return write_json_file(root / "factor-config.json", {
        "run_name": "devils_committee_factor_selection",
        "output_root": str(root / FACTOR_SKILL / "raw"),
        "random_seed": 42,
        "mode": "mrmr",
        "selection_count": 6,
        "input": {"feature_path": feature_path, "label_path": label_path},
        "data": {"date_col": "date", "ticker_col": "symbol", "label_col": "y"},
        "validation": {
            "method": "fixed",
            "train_start": 20240101,
            "train_end": 20250131,
            "valid_start": 20250210,
            "valid_end": 20251231,
            "embargo_days": 5,
        },
        "mrmr": {"relevance": "f", "redundancy": "c", "denominator": "mean"},
    })


def write_hpo_config(feature_path: str, label_path: str) -> str:
    root = Path(CONFIG.precomputed_dir)
    return write_json_file(root / "hpo-config.json", {
        "output_root": str(root / HPO_SKILL / "raw"),
        "config": {
            "task": {"name": "devils_committee_hpo", "seed": 42},
            "input": {"feature_path": feature_path, "label_path": label_path},
            "data": {
                "start_date": 20240101,
                "end_date": 20260724,
                "date_col": "date",
                "ticker_col": "symbol",
                "label_col": "y",
                "strict_point_in_time": True,
                "compute_hash": True,
            },
            "search": {
                "model_type": "lgbm",
                "method": "adaptive_tpe",
                "max_trials": 12,
                "max_rounds": 3,
                "trials_per_round": 4,
                "random_start_trials": 4,
                "seed": 42,
                "space": {
                    "num_leaves": {"type": "choice", "values": [15, 31, 63]},
                    "learning_rate": {"type": "loguniform", "low": 0.01, "high": 0.12},
                    "n_estimators": {"type": "choice", "values": [100, 200, 400]},
                    "subsample": {"type": "uniform", "low": 0.7, "high": 1.0},
                    "colsample_bytree": {"type": "uniform", "low": 0.7, "high": 1.0},
                },
            },
            "model": {"type": "lgbm"},
            "validation": {
                "method": "fixed_train_valid_test",
                "train_start": 20240101,
                "train_end": 20250131,
                "valid_start": 20250210,
                "valid_end": 20251231,
                "test_start": 20260112,
                "test_end": 20260724,
                "embargo_days": 5,
                "min_assets_per_date": 5,
            },
            "training": {"label_window": 5},
            "evaluation": {"inner_loop": "fast_evaluator", "objective": "rankic_ir"},
            "llm": {"enabled": False},
            "final_selector": {"enabled": False},
        },
    })


def run_precompute_command(skill_id: str, entry: str, config_path: str) -> None:
    script = Path(CONFIG.quantskills_dir) / skill_id / "scripts" / entry
    subprocess.run(
        [sys.executable, str(script), "--input", config_path],
        cwd=str(script.parents[1]),
        check=True,
        timeout=900,
    )


def current_commit() -> str:
    if CONFIG.build_commit:
        return CONFIG.build_commit
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def collect_result(
    skill_id: str,
    hashes: list[str],
    commit: str,
    universe: list[str],
    feature_path: str,
    label_path: str,
) -> None:
    root = Path(CONFIG.precomputed_dir) / skill_id
    if skill_id == FACTOR_SKILL:
        selected_path = max((root / "raw").rglob("selected_factors.json"), key=lambda path: path.stat().st_mtime)
        run_dir = selected_path.parent
        selected = json.loads(selected_path.read_text(encoding="utf-8"))
        run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        payload = {
            "selected_factors": selected["selected_factors"],
            "metrics": {
                "n_obs": selected.get("n_obs", run_manifest.get("num_rows", 0)),
                "train_start": "20240101", "train_end": "20250131",
                "valid_start": "20250210", "valid_end": "20251231",
            },
            "warnings": [],
        }
    else:
        manifest_path = max((root / "raw").rglob("search_manifest.json"), key=lambda path: path.stat().st_mtime)
        run_dir = manifest_path.parent
        best_params = json.loads((run_dir / "best_params.json").read_text(encoding="utf-8"))
        trials = [
            json.loads(line)
            for line in (run_dir / "trials.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        successful = [row for row in trials if row.get("status") == "ok"]
        failed = [row for row in trials if row.get("status") != "ok"]
        if not successful:
            raise RuntimeError("HPO produced no successful trials")
        payload = {
            "best_params": best_params,
            "metrics": {
                "successful_trials": len(successful),
                "failed_trials": len(failed),
                "seed": 42,
                "validation_score": max(float(row["score"]) for row in successful),
            },
            "warnings": [],
        }
    write_json_file(root / "result.json", payload)
    write_json_file(root / "devils-committee-manifest.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit,
        "dataset_hashes": hashes,
        "universe": universe,
        "source_files": {
            str(Path(feature_path).relative_to(CONFIG.precomputed_dir)): file_sha256(Path(feature_path)),
            str(Path(label_path).relative_to(CONFIG.precomputed_dir)): file_sha256(Path(label_path)),
        },
        "result_file": "result.json",
    })


def main() -> int:
    request = ResearchRequest(
        symbol="600519.SH",
        market="cn",
        question="prepare cross-sectional research",
        start_date=os.environ.get("PRECOMPUTE_START", "20240101"),
        end_date=os.environ.get("PRECOMPUTE_END", "20260724"),
    )
    try:
        feature_path, label_path, hashes = build_factor_tables(request, DEFAULT_UNIVERSE)
    except RuntimeError:
        print("precompute stopped: PandaData evidence unavailable")
        return 1
    factor_config = write_factor_config(feature_path, label_path)
    hpo_config = write_hpo_config(feature_path, label_path)
    run_precompute_command(FACTOR_SKILL, "run_factor_selection.py", factor_config)
    run_precompute_command(HPO_SKILL, "run_hpo_search.py", hpo_config)
    commit = current_commit()
    collect_result(FACTOR_SKILL, hashes, commit, DEFAULT_UNIVERSE, feature_path, label_path)
    collect_result(HPO_SKILL, hashes, commit, DEFAULT_UNIVERSE, feature_path, label_path)
    return 0
```

输入表列名固定为 `date`、`symbol`、因子列和标签列 `y`，标签为后复权收盘价的 5 个交易日未来收益。脚本输出目录只允许位于 `PRECOMPUTED_DIR`。

把以下内容加入 `.gitignore`：

```text
var/cache/
var/precomputed/
var/live-records/
```

- [ ] **Step 5: 将两个结果加入共享证据**

在 `SkillRunner.prepare()` 的在线结果之后加入：

```python
store = PrecomputedStore(CONFIG.precomputed_dir, CONFIG.build_commit)
precomputed = [
    store.load("skill-factor-ranking-sage", request.symbol),
    store.load("skill-model-hpo-evidence-driven", request.symbol),
]
all_results = [*online, *precomputed]
return ResearchEvidence(request, bundle, {item.skill_id: item for item in all_results})
```

- [ ] **Step 6: 运行提前计算读取测试**

Run: `.venv/bin/python -m pytest tests/test_precomputed_skills.py tests/test_online_skills.py -v`

Expected: PASS；哈希或提交号不符时始终为 `insufficient-evidence`。

- [ ] **Step 7: 提交**

```bash
git add backend/skills/precomputed.py backend/skills/runner.py scripts/precompute_research.py tests/test_precomputed_skills.py .gitignore
git commit -m "feat: consume verified precomputed skills"
```

### Task 6: 让 Agent 只解释真实 Skill 结果

**Files:**
- Modify: `backend/models.py`
- Rewrite: `backend/agents.py`
- Rewrite: `backend/skills/runner.py`
- Modify: `backend/llm.py`
- Modify: `backend/plain.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_agents.py`
- Modify: `tests/test_audit_edges.py`
- Modify: `tests/test_llm.py`

- [ ] **Step 1: 写来源引用和虚构 Skill 清除测试**

在 `tests/conftest.py` 增加共享证据：

```python
import copy
import pytest

from backend.research_request import ResearchRequest
from backend.skills.contracts import DatasetArtifact, MarketDataBundle, SkillFinding, SkillResult
from backend.skills.runner import ResearchEvidence

TEST_SKILLS = [
    "skill-corporate-action-adjustment-auditor",
    "skill-survivorship-universe-auditor",
    "skill-portfolio-liquidity-stress-test",
    "skill-index-rebalance-event-study",
    "skill-factor-ranking-sage",
    "skill-model-hpo-evidence-driven",
]


def _research_evidence() -> ResearchEvidence:
    artifact = DatasetArtifact(
        name="daily", method="get_stock_daily", params={}, path="/tmp/daily.parquet",
        sha256="daily-hash", rows=30, mode="mock",
        fetched_at="2026-07-24T00:00:00+00:00",
    )
    bundle = MarketDataBundle("600519.SH", "success", "mock", {"daily": artifact})
    results = {
        skill_id: SkillResult(
            skill_id=skill_id,
            mode="mock",
            status="success",
            duration_ms=1,
            dataset_hashes=["daily-hash"],
            metrics={"sample_size": 30},
            findings=[SkillFinding(f"{skill_id} checked", ["daily"], 0.8)],
        )
        for skill_id in TEST_SKILLS
    }
    request = ResearchRequest("600519.SH", "cn", "分析风险", "20240101", "20260724")
    return ResearchEvidence(request, bundle, results)


@pytest.fixture
def evidence_fixture():
    return _research_evidence()


@pytest.fixture
def evidence_with_missing_factor():
    evidence = copy.deepcopy(_research_evidence())
    evidence.results["skill-factor-ranking-sage"].status = "insufficient-evidence"
    evidence.results["skill-factor-ranking-sage"].findings = []
    evidence.results["skill-factor-ranking-sage"].warnings = ["factor report unavailable"]
    return evidence


@pytest.fixture
def evidence_with_missing_survivorship():
    evidence = copy.deepcopy(_research_evidence())
    evidence.results["skill-survivorship-universe-auditor"].status = "insufficient-evidence"
    evidence.results["skill-survivorship-universe-auditor"].findings = []
    evidence.results["skill-survivorship-universe-auditor"].warnings = ["delisting_return unavailable"]
    return evidence
```

创建 `tests/test_agents.py`：

```python
import asyncio

from backend.agents import BullAgent, BearAgent, MacroAgent, RiskAgent, AuditAgent
from backend.llm import MockLLM
from backend.skills.runner import ResearchEvidence

ALLOWED = {
    "skill-corporate-action-adjustment-auditor",
    "skill-survivorship-universe-auditor",
    "skill-portfolio-liquidity-stress-test",
    "skill-index-rebalance-event-study",
    "skill-factor-ranking-sage",
    "skill-model-hpo-evidence-driven",
}


def test_every_claim_cites_only_integrated_skills(evidence_fixture):
    agents = [BullAgent(MockLLM()), BearAgent(MockLLM()), MacroAgent(MockLLM()), RiskAgent(MockLLM())]
    claims = []
    for agent in agents:
        claims.extend(asyncio.run(agent.argue(evidence_fixture)))
    assert claims
    assert all(set(claim.skills_used) <= ALLOWED for claim in claims)
    for claim in claims:
        assert claim.evidence
        assert all(item.skill_id in ALLOWED for item in claim.evidence)
        assert all(item.dataset_hashes for item in claim.evidence)


def test_insufficient_result_is_described_as_uncertain(evidence_with_missing_factor):
    claims = asyncio.run(BullAgent(MockLLM()).argue(evidence_with_missing_factor))
    assert claims
    assert claims[0].confidence <= 0.35
    assert "证据不足" in claims[0].text


def test_audit_does_not_turn_missing_evidence_into_pass(evidence_with_missing_survivorship):
    claims = asyncio.run(RiskAgent(MockLLM()).argue(evidence_with_missing_survivorship))
    verdicts = asyncio.run(AuditAgent(MockLLM()).audit(evidence_with_missing_survivorship, claims))
    assert any(item.status == "thin_data" for item in verdicts)
```

在 `tests/test_llm.py` 增加模型失败的固定输出测试：

```python
def test_llm_failure_returns_structured_fallback_without_fake_numbers():
    llm = _llm_with(_ErrResp({}, raises=True))
    text = llm.argue(side="bull", symbol="600519.SH", evidence=[])
    assert "模型说明暂不可用" in text
    assert not any(ch.isdigit() for ch in text)
```

- [ ] **Step 2: 运行测试，确认当前 Agent 仍引用未接入的名称**

Run: `.venv/bin/python -m pytest tests/test_agents.py tests/test_audit_edges.py tests/test_llm.py -v`

Expected: FAIL；当前代码仍引用 `skill-residual-guided-factor-selection`、`skill-us-sector-rotation`、`skill-holder-structure-scan`、`skill-dalio-all-weather` 和 `skill-templeton-global-contrarian`。

- [ ] **Step 3: 扩展 Evidence 字段，保留向后兼容的 JSON 名称**

在 `backend/models.py` 把 `Evidence` 改为：

```python
@dataclass
class Evidence:
    skill_id: str
    summary: str
    status: str
    mode: str
    dataset_hashes: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)

    @property
    def skill(self) -> str:
        return self.skill_id

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["skill"] = self.skill_id
        return payload
```

增加转换函数：

```python
def evidence_from_result(result: SkillResult) -> Evidence:
    summaries = [item.claim for item in result.findings]
    summary = "；".join(summaries[:2]) or "该项没有可发布的结论"
    refs = sorted({ref for item in result.findings for ref in item.evidence_refs})
    return Evidence(
        skill_id=result.skill_id,
        summary=summary,
        status=result.status,
        mode=result.mode,
        dataset_hashes=result.dataset_hashes,
        evidence_refs=refs,
        metrics=result.metrics,
        assumptions=result.assumptions,
    )
```

- [ ] **Step 4: 重写四个论证 Agent 的证据选择**

四个角色只使用下列组合：

```python
ROLE_SKILLS = {
    "bull": [
        "skill-factor-ranking-sage",
        "skill-corporate-action-adjustment-auditor",
    ],
    "bear": [
        "skill-portfolio-liquidity-stress-test",
        "skill-index-rebalance-event-study",
    ],
    "macro": [
        "skill-index-rebalance-event-study",
        "skill-factor-ranking-sage",
    ],
    "risk": [
        "skill-portfolio-liquidity-stress-test",
        "skill-model-hpo-evidence-driven",
        "skill-survivorship-universe-auditor",
        "skill-corporate-action-adjustment-auditor",
    ],
}
```

基类实现统一论证：

```python
class _Base:
    side = ""

    def __init__(self, llm) -> None:
        self.llm = llm

    async def argue(self, evidence: ResearchEvidence) -> list[Claim]:
        chosen = [
            evidence.results[skill_id]
            for skill_id in ROLE_SKILLS[self.side]
            if skill_id in evidence.results
        ]
        items = [evidence_from_result(item) for item in chosen]
        insufficient = [item for item in chosen if item.status != "success"]
        if not items:
            return []
        text = self.llm.argue(
            side=self.side,
            symbol=evidence.request.symbol,
            evidence=[item.to_dict() for item in items],
        )
        if insufficient:
            text = f"证据不足：{text}"
        return [Claim(
            id=f"{self.side}-1",
            agent=self.__class__.__name__.removesuffix("Agent"),
            side=self.side,
            text=text,
            confidence=0.3 if insufficient else 0.65,
            evidence=items,
            skills_used=[item.skill_id for item in items],
        )]
```

- [ ] **Step 5: 重写审计映射，不再重新计算启发式数字**

`AuditAgent.audit()` 直接读取三个审计结果：

```python
AUDIT_STATUS = {
    "skill-survivorship-universe-auditor": "selection_bias",
    "skill-model-hpo-evidence-driven": "suspected_overfit",
    "skill-corporate-action-adjustment-auditor": "bad_data",
}


async def audit(self, evidence: ResearchEvidence, claims: list[Claim]) -> list[AuditVerdict]:
    verdicts = []
    for claim in claims:
        relevant = [
            evidence.results[skill_id]
            for skill_id in AUDIT_STATUS
            if skill_id in evidence.results
            and (skill_id in claim.skills_used or claim.side in {"bull", "risk"})
        ]
        thin = next((item for item in relevant if item.status == "insufficient-evidence"), None)
        flagged = next((item for item in relevant if item.findings), None)
        if thin:
            status, source, severity = "thin_data", thin, "low"
        elif flagged:
            status, source, severity = AUDIT_STATUS[flagged.skill_id], flagged, "medium"
        else:
            status, source, severity = "pass", None, "none"
        detail = source.to_dict() if source else {}
        verdicts.append(AuditVerdict(
            claim_id=claim.id,
            status=status,
            reason=self.llm.audit_reason(status=status, symbol=evidence.request.symbol, detail=detail),
            audit_skill=source.skill_id if source else "",
            severity=severity,
            remediation="补齐缺失字段并重新运行对应 QuantSkill。" if source else "",
            provenance=source.mode if source else evidence.bundle.mode,
            plain=plain_audit(status),
        ))
    return verdicts
```

- [ ] **Step 6: 删除旧接口和虚构来源**

从 `backend/skills/runner.py` 删除 `regime()`、内部 `event_study()`、内部 `liquidity_stress()`、`_survivorship_mock()`、`_data_quality_mock()` 和 `audit_hpo()` 的启发式实现。mock 模式改为生成结构一致、明确标为 `mode="mock"` 的六个 `SkillResult`，供默认测试和离线演示使用。

mock 结果使用以下固定构建器，不能经过在线 CLI：

```python
MOCK_SKILL_IDS = [
    "skill-corporate-action-adjustment-auditor",
    "skill-survivorship-universe-auditor",
    "skill-portfolio-liquidity-stress-test",
    "skill-index-rebalance-event-study",
    "skill-factor-ranking-sage",
    "skill-model-hpo-evidence-driven",
]


def build_mock_results(bundle: MarketDataBundle) -> dict[str, SkillResult]:
    findings = {
        "skill-portfolio-liquidity-stress-test": [
            SkillFinding("mock liquidity estimate", ["daily"], 0.5)
        ],
        "skill-index-rebalance-event-study": [
            SkillFinding("mock index event estimate", ["daily"], 0.5)
        ],
        "skill-factor-ranking-sage": [
            SkillFinding("mock factor ranking", ["daily"], 0.5)
        ],
    }
    return {
        skill_id: SkillResult(
            skill_id=skill_id,
            mode="mock",
            status="success",
            duration_ms=0,
            dataset_hashes=bundle.dataset_hashes,
            findings=findings.get(skill_id, []),
            warnings=["offline deterministic mock; not valid for public evidence"],
        )
        for skill_id in MOCK_SKILL_IDS
    }
```

`SkillRunner.prepare()` 的首个分支改为：

```python
bundle = await asyncio.to_thread(build_market_data_bundle, request)
if bundle.status != "success":
    return ResearchEvidence(request, bundle, {})
if bundle.mode == "mock":
    return ResearchEvidence(request, bundle, build_mock_results(bundle))
```

`backend/llm.py` 的错误文本固定为：

```python
return "（模型说明暂不可用；请直接查看下方 Skill 结果、数据来源和风险提示。）"
```

日志只记录错误类型：

```python
logging.getLogger("devils-committee").warning("LLM call failed: %s", type(exc).__name__)
```

- [ ] **Step 7: 运行 Agent 和模型测试**

Run: `.venv/bin/python -m pytest tests/test_agents.py tests/test_audit_edges.py tests/test_llm.py tests/test_openai_integration.py -v`

Expected: PASS；所有 claim 只引用六个已接入的 Skill，缺失证据不会得到 `pass`。

- [ ] **Step 8: 提交**

```bash
git add backend/models.py backend/agents.py backend/skills/runner.py backend/llm.py backend/plain.py tests/conftest.py tests/test_agents.py tests/test_audit_edges.py tests/test_llm.py tests/test_openai_integration.py
git commit -m "refactor: ground every agent claim in skill results"
```

### Task 7: 改造编排时间限制和失败结果

**Files:**
- Rewrite: `backend/orchestration.py`
- Modify: `backend/models.py`
- Modify: `tests/test_orchestration.py`
- Modify: `tests/test_openai_integration.py`

- [ ] **Step 1: 写一次取数、10 分钟限制和不支持市场测试**

在 `tests/test_orchestration.py` 增加：

```python
def test_budget_is_ten_minutes_with_two_minute_skill_limit():
    assert GLOBAL_BUDGET_SEC == 10 * 60
    assert PER_AGENT_TIMEOUT_SEC == 120


def test_prepare_runs_once_for_all_agents(monkeypatch, evidence_fixture):
    calls = {"n": 0}

    async def prepare(self, request):
        calls["n"] += 1
        return evidence_fixture

    monkeypatch.setattr(SkillRunner, "prepare", prepare)
    result = asyncio.run(DebateOrchestrator().run("600519 多空"))
    assert calls["n"] == 1
    assert result.meta["data_status"] in {"success", "insufficient-evidence"}


def test_us_input_returns_structured_insufficient_evidence():
    result = asyncio.run(DebateOrchestrator().run("分析 NVDA"))
    assert result.meta["symbol"] == "NVDA"
    assert result.meta["data_status"] == "insufficient-evidence"
    assert result.meta["supported_market"] is False
    assert result.claims == []
    assert result.disclaimer


def test_prepare_failure_does_not_create_mock_live_claims(monkeypatch):
    async def broken(self, request):
        raise RuntimeError("private service detail")

    monkeypatch.setattr(SkillRunner, "prepare", broken)
    result = asyncio.run(DebateOrchestrator().run("600519 多空"))
    assert result.meta["data_status"] == "error"
    assert result.claims == []
    assert "private service detail" not in repr(result.to_dict())
```

- [ ] **Step 2: 运行测试，确认旧编排仍使用 18 分钟和重复同步调用**

Run: `.venv/bin/python -m pytest tests/test_orchestration.py tests/test_openai_integration.py -v`

Expected: FAIL；常量仍为 18 分钟和 4 分钟，Agent 也尚未接收 `ResearchEvidence`。

- [ ] **Step 3: 建立统一的不足结果和错误结果**

在 `backend/orchestration.py` 增加：

```python
GLOBAL_BUDGET_SEC = CONFIG.request_budget_sec
PER_AGENT_TIMEOUT_SEC = 120
MAX_AUDIT_ROUNDS = 1


def _empty_result(
    request: ResearchRequest,
    *,
    data_status: str,
    reason: str,
    elapsed_sec: float,
) -> DebateResult:
    return enforce(DebateResult(
        topic=request.question,
        claims=[],
        verdicts=[],
        consensus=[],
        open_disagreements=[],
        risk_boundaries=[reason, "当前结果没有使用模拟数据代替真实证据。"],
        elapsed_sec=elapsed_sec,
        meta={
            "symbol": request.symbol,
            "supported_market": request.supported,
            "data_status": data_status,
            "gives_investment_advice": False,
            "recommendation": None,
            "skills_manifest": {"all_skills": [], "results": []},
        },
    ))
```

- [ ] **Step 4: 一次准备共享证据，再并行运行四个角色**

`DebateOrchestrator.stream()` 的前半段改为：

```python
async def stream(self, topic: str | ResearchRequest, pace: float = 0.0):
    request = topic if isinstance(topic, ResearchRequest) else ResearchRequest.from_payload({"topic": topic})
    started = _mono()
    if not request.supported:
        self.result = _empty_result(
            request,
            data_status="insufficient-evidence",
            reason="当前真实研究只支持 A 股代码。",
            elapsed_sec=round(_mono() - started, 2),
        )
        yield {"stage": "result", "result": self.result.to_dict()}
        return
    try:
        evidence = await asyncio.wait_for(
            self.runner.prepare(request),
            timeout=GLOBAL_BUDGET_SEC,
        )
    except asyncio.TimeoutError:
        self.result = _empty_result(
            request,
            data_status="error",
            reason="研究请求超过内部时间限制。",
            elapsed_sec=round(_mono() - started, 2),
        )
        yield {"stage": "result", "result": self.result.to_dict()}
        return
    except Exception:
        self.result = _empty_result(
            request,
            data_status="error",
            reason="研究数据暂不可用，请稍后重试。",
            elapsed_sec=round(_mono() - started, 2),
        )
        yield {"stage": "result", "result": self.result.to_dict()}
        return
    if evidence.bundle.status != "success":
        self.result = _empty_result(
            request,
            data_status="insufficient-evidence",
            reason="当前没有足够的授权数据支持研究。",
            elapsed_sec=round(_mono() - started, 2),
        )
        yield {"stage": "result", "result": self.result.to_dict()}
        return

    agents = [self.bull, self.bear, self.macro, self.risk]
    tasks = [asyncio.create_task(self._argue(agent, evidence)) for agent in agents]
```

`_argue()` 改为调用 `agent.argue(evidence)`，超时后只返回空 claim；Audit 接收同一 `evidence`。不再让 Bull 单独返回 `factor_payload`。

构造函数改为新的 Agent 参数：

```python
self.runner = SkillRunner()
self.llm = get_llm()
self.bull = BullAgent(self.llm)
self.bear = BearAgent(self.llm)
self.macro = MacroAgent(self.llm)
self.risk = RiskAgent(self.llm)
self.audit = AuditAgent(self.llm)
self.chair = ChairAgent(self.llm)
```

`audit_claims()` 同样先构造或接收 `ResearchRequest`，只调用一次 `self.runner.prepare(request)`，再用同一份 `ResearchEvidence` 生成 claims 和 verdicts。不支持市场、数据失败和超时的返回结构与 `run()` 一致。

- [ ] **Step 5: 从统一结果生成来源清单**

`_skills_manifest()` 改为：

```python
def _skills_manifest(self, evidence: ResearchEvidence, claims: list[Claim]) -> dict:
    used_by: dict[str, set[str]] = {}
    for claim in claims:
        for skill_id in claim.skills_used:
            used_by.setdefault(skill_id, set()).add(claim.agent)
    results = []
    for skill_id, result in sorted(evidence.results.items()):
        results.append({
            "skill_id": skill_id,
            "status": result.status,
            "mode": result.mode,
            "duration_ms": result.duration_ms,
            "dataset_hashes": result.dataset_hashes,
            "used_by": sorted(used_by.get(skill_id, set())),
            "assumptions": result.assumptions,
            "warnings": result.warnings,
        })
    return {
        "data": {
            "symbol": evidence.request.symbol,
            "status": evidence.bundle.status,
            "mode": evidence.bundle.mode,
            "dataset_hashes": evidence.bundle.dataset_hashes,
        },
        "results": results,
        "all_skills": sorted(evidence.results),
    }
```

结果 `meta` 同时增加 `data_status`、`supported_market` 和 `modes`。`audit_engine` 改为列出实际出现的 `live`、`cache`、`precomputed` 或 `mock`，不再使用 `real-quant`、`real-cli`、`mock-fallback`。

- [ ] **Step 6: 运行编排测试**

Run: `.venv/bin/python -m pytest tests/test_orchestration.py tests/test_openai_integration.py -v`

Expected: PASS；一次请求只准备一次数据，不支持市场返回结构化不足结果。

- [ ] **Step 7: 提交**

```bash
git add backend/orchestration.py backend/models.py tests/test_orchestration.py tests/test_openai_integration.py
git commit -m "feat: enforce research budgets and safe failures"
```

### Task 8: 更新 A2A、Agent Card、前端和三个 A 股示例

**Files:**
- Modify: `backend/a2a_server.py`
- Modify: `agent-card.json`
- Modify: `web/index.html`
- Modify: `scripts/demo.py`
- Modify: `scripts/demo_cheatsheet.py`
- Modify: `tests/test_server.py`
- Modify: `tests/frontend.test.mjs`
- Rewrite: `tests/test_examples.py`
- Keep: `tests/examples/600519_moutai_baddata.json`
- Delete: `tests/examples/nvda_overfit_bounce.json`
- Delete: `tests/examples/tsla_all_pass.json`
- Create: `tests/examples/300750_catl_research.json`
- Create: `tests/examples/601318_pingan_research.json`

- [ ] **Step 1: 写结构化 A2A 和 Agent Card 失败测试**

在 `tests/test_server.py` 增加或改写：

```python
from backend.models import DebateResult


def _minimal_result(symbol: str) -> DebateResult:
    return DebateResult(
        topic="test",
        disclaimer="仅供研究，不构成投资建议。",
        meta={
            "symbol": symbol,
            "data_status": "success",
            "supported_market": True,
            "gives_investment_advice": False,
            "recommendation": None,
            "skills_manifest": {"all_skills": [], "results": []},
        },
    )


def test_structured_research_fields_reach_orchestrator(monkeypatch):
    seen = {}

    async def fake_run(self, request):
        seen["request"] = request
        return _minimal_result(request.symbol)

    monkeypatch.setattr(a2a_server.DebateOrchestrator, "run", fake_run)
    response = client.post("/a2a", json={
        "skill": "debate_case",
        "symbol": "300750.SZ",
        "question": "流动性风险如何？",
        "start_date": "20240101",
        "end_date": "20260724",
        "portfolio_value": 800000,
        "spread_bps": 9,
    })
    assert response.status_code == 200
    assert seen["request"].symbol == "300750.SZ"
    assert seen["request"].portfolio_value == 800000


def test_agent_card_has_three_a_share_examples_and_no_placeholder():
    card = client.get("/.well-known/agent-card.json").json()
    rendered = json.dumps(card, ensure_ascii=False)
    assert "600519.SH" in rendered
    assert "300750.SZ" in rendered
    assert "601318.SH" in rendered
    assert "NVDA" not in rendered and "TSLA" not in rendered and "AAPL" not in rendered
    assert "your-host" not in rendered and "your-repo" not in rendered


def test_unsupported_market_returns_explained_result_not_server_error():
    response = client.post("/a2a", json={"topic": "分析 NVDA"})
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["meta"]["data_status"] == "insufficient-evidence"
    assert result["claims"] == []
```

把 `tests/test_examples.py` 改为检查可重复的结构，而不是依赖旧启发式状态：

```python
def test_examples_replay_matches_contract():
    for path in _load():
        example = json.loads(Path(path).read_text(encoding="utf-8"))
        result = asyncio.run(DebateOrchestrator().run(example["input"]["topic"])).to_dict()
        expected = example["expected"]
        assert result["meta"]["symbol"] == expected["symbol"]
        assert result["disclaimer"]
        assert set(result["meta"]["skills_manifest"]["all_skills"]) == set(expected["skill_ids"])
        assert result["meta"]["gives_investment_advice"] is False
        for item in result["meta"]["skills_manifest"]["results"]:
            assert item["mode"] in {"mock", "live", "cache", "precomputed"}
            assert item["status"] in {"success", "insufficient-evidence", "error"}
```

- [ ] **Step 2: 运行服务和示例测试，确认旧美股内容仍存在**

Run: `.venv/bin/python -m pytest tests/test_server.py tests/test_examples.py -v`

Expected: FAIL；Agent Card、测试和页面仍包含美股示例，A2A 也没有构造 `ResearchRequest`。

- [ ] **Step 3: 让 A2A 解析完整研究请求**

在 `backend/a2a_server.py` 增加：

```python
def extract_research_request(body: dict) -> ResearchRequest:
    payload = dict(body)
    topic = extract_topic(body)
    if topic and not payload.get("topic"):
        payload["topic"] = topic
    return ResearchRequest.from_payload(payload)
```

`a2a()` 中用：

```python
research_request = extract_research_request(body)
if not research_request.question:
    raise HTTPException(status_code=422, detail="no task/topic found in message")
```

随后把 `research_request` 传给 `run()` 或 `audit_claims()`。响应错误仍只允许 `internal error`、`invalid request`、`unauthorized` 三类公开文字。

- [ ] **Step 4: 改成真实 Agent Card 信息和 A 股示例**

`agent-card.json` 至少使用以下内容：

```json
{
  "name": "Devil's Committee — AI Investment Debate Coach",
  "description": "A multi-agent A-share research coach that explains evidence, audits data and model risks, and never gives buy or sell instructions.",
  "version": "0.2.0",
  "url": "http://localhost:8080/a2a",
  "provider": {
    "organization": "Team ADVX2026",
    "url": "https://github.com/serein431/devils-committee"
  },
  "documentationUrl": "https://github.com/serein431/devils-committee/blob/main/README.md",
  "defaultInputModes": ["text/plain", "application/json"],
  "defaultOutputModes": ["application/json", "text/plain"],
  "capabilities": {"streaming": true, "pushNotifications": false}
}
```

`debate_case.examples` 改为：

```json
[
  "研究 600519.SH 的复权、分红、因子和流动性风险",
  "研究 300750.SZ 的成长因子、波动、流动性和指数事件",
  "研究 601318.SH 的分红、股票池和风险证据"
]
```

服务继续在返回 Agent Card 时用 `PUBLIC_URL` 覆盖 `url`；`documentationUrl` 使用 `CONFIG.repository_url` 生成，避免部署后写死错误地址。

- [ ] **Step 5: 替换离线示例文件和页面快捷输入**

两个新示例文件使用同一结构，分别只改 `topic` 与 `symbol`：

```json
{
  "input": {
    "skill": "debate_case",
    "topic": "研究 300750.SZ 的成长因子、波动、流动性和指数事件"
  },
  "expected": {
    "symbol": "300750.SZ",
    "skill_ids": [
      "skill-corporate-action-adjustment-auditor",
      "skill-survivorship-universe-auditor",
      "skill-portfolio-liquidity-stress-test",
      "skill-index-rebalance-event-study",
      "skill-factor-ranking-sage",
      "skill-model-hpo-evidence-driven"
    ]
  }
}
```

`601318_pingan_research.json` 的输入改为“研究 601318.SH 的分红、股票池和风险证据”。`600519_moutai_baddata.json` 删除整段 `full_output_sample`，改成相同的契约检查结构。

`web/index.html` 的 placeholder 和 `EX` 数组只保留：

```javascript
const EX = [
  "600519.SH 复权、分红、因子和流动性风险",
  "300750.SZ 成长因子、波动、流动性和指数事件",
  "601318.SH 分红、股票池和风险证据"
];
```

`scripts/demo.py`、`scripts/demo_cheatsheet.py` 使用同样三个代码，不再承诺某个标的一定得到某种审计状态。

- [ ] **Step 6: 更新前端测试并运行**

`tests/frontend.test.mjs` 增加断言：

```javascript
assert.match(html, /600519\.SH/);
assert.match(html, /300750\.SZ/);
assert.match(html, /601318\.SH/);
assert.doesNotMatch(html, /AAPL|NVDA|TSLA/);
```

Run: `.venv/bin/python -m pytest tests/test_server.py tests/test_examples.py -v && ./scripts/test_frontend.sh`

Expected: Python 和前端测试均 PASS。

- [ ] **Step 7: 提交**

```bash
git add backend/a2a_server.py agent-card.json web/index.html scripts/demo.py scripts/demo_cheatsheet.py tests/test_server.py tests/frontend.test.mjs tests/test_examples.py tests/examples
git commit -m "feat: publish three A-share research examples"
```

### Task 9: 增加真实联调、缓存预热和脱敏记录

**Files:**
- Create: `tests/test_live_integration.py`
- Modify: `scripts/setup_real.py`
- Modify: `scripts/warm_cache.py`
- Modify: `scripts/smoke_a2a.py`
- Create: `scripts/record_live_examples.py`
- Create: `docs/LIVE_INTEGRATION.md`

- [ ] **Step 1: 写默认跳过的真实联调测试**

创建 `tests/test_live_integration.py`：

```python
import asyncio
import os

import pytest

from backend import llm
from backend.orchestration import DebateOrchestrator
from backend.research_request import ResearchRequest
from backend.skills.panda import build_market_data_bundle
from backend.skills.runner import SkillRunner

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_INTEGRATION") != "1",
    reason="set RUN_LIVE_INTEGRATION=1 to run paid or credentialed checks",
)


def test_live_deepseek_v4_pro_minimal_reply():
    model = llm.get_llm()
    assert model.mode == "openai"
    text = model._chat(
        "只回复 OK，不输出任何投资内容。",
        "ping",
    )
    assert text.strip()
    assert "模型说明暂不可用" not in text


def test_live_pandadata_daily_bundle():
    request = ResearchRequest("600519.SH", "cn", "数据检查", "20260716", "20260724")
    bundle = build_market_data_bundle(request)
    assert bundle.status == "success"
    assert bundle.datasets["daily"].rows > 0
    assert bundle.datasets["daily"].mode in {"live", "cache"}


@pytest.mark.parametrize("symbol", ["600519.SH", "300750.SZ", "601318.SH"])
def test_live_six_skill_results_exist(symbol):
    request = ResearchRequest(symbol, "cn", "完整研究", "20240101", "20260724")
    evidence = asyncio.run(SkillRunner().prepare(request))
    assert set(evidence.results) == {
        "skill-corporate-action-adjustment-auditor",
        "skill-survivorship-universe-auditor",
        "skill-portfolio-liquidity-stress-test",
        "skill-index-rebalance-event-study",
        "skill-factor-ranking-sage",
        "skill-model-hpo-evidence-driven",
    }
    assert all(item.mode != "mock" for item in evidence.results.values())


@pytest.mark.parametrize("symbol", ["600519.SH", "300750.SZ", "601318.SH"])
def test_live_a2a_research_is_repeatable(symbol):
    result = asyncio.run(DebateOrchestrator().run(f"研究 {symbol} 的多空证据和风险"))
    assert result.meta["symbol"] == symbol
    assert result.meta["data_status"] == "success"
    assert result.disclaimer
    assert result.elapsed_sec <= 600
```

- [ ] **Step 2: 运行默认测试，确认真实测试不会进入普通 CI**

Run: `.venv/bin/python -m pytest tests/test_live_integration.py -v`

Expected: 全部 SKIPPED，原因中包含 `RUN_LIVE_INTEGRATION=1`。

- [ ] **Step 3: 更新准备检查和缓存预热**

`scripts/warm_cache.py` 的默认代码改为：

```python
DEFAULT = ["600519.SH", "300750.SZ", "601318.SH"]
```

预热脚本调用 `build_market_data_bundle()`，逐个显示数据集名、行数、`live/cache` 和哈希前 8 位，不显示请求参数中的账号或任何请求头。任一标的的 `daily` 不可用时退出码为 1。

`scripts/setup_real.py --check` 增加以下检查，但错误只输出类型：

```python
checks = {
    "python_3_12": sys.version_info[:2] == (3, 12),
    "ark_endpoint_id": bool(env.get("LLM_MODEL")),
    "panda_credentials": all(env.get(key) for key in ("DEFAULT_USERNAME", "DEFAULT_PASSWORD")),
    "seven_skill_repositories": all((skill_root / name / "scripts").is_dir() for name in REQUIRED_REPOS),
    "precomputed_manifests": all((precomputed_root / name / "devils-committee-manifest.json").is_file() for name in PRECOMPUTED_SKILLS),
}
```

- [ ] **Step 4: 创建脱敏示例记录脚本**

`scripts/record_live_examples.py` 对三个请求调用本地或公网 A2A，并写入 `var/live-records/<symbol>/`：

```python
SENSITIVE_KEYS = {
    "authorization", "cookie", "llm_api_key", "default_username",
    "default_password", "a2a_bearer_token",
}


def sanitize(value):
    if isinstance(value, dict):
        return {
            key: "[redacted]" if key.lower() in SENSITIVE_KEYS else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value
```

每个目录保存 `request.json`、`response.json`、`skills.json` 和 `README.md`。`README.md` 写明运行时间、服务 URL 的主机名、总耗时、数据模式和六个状态，不保存 Bearer Token 或 HTTP 请求头。

- [ ] **Step 5: 更新公网检查脚本**

`scripts/smoke_a2a.py` 使用 `timeout=610`，默认输入 `600519.SH`，并新增：

```python
check("research stays inside 10-minute budget", r["elapsed_sec"] <= 600)
check("no mock result in live smoke", all(
    item["mode"] != "mock"
    for item in r["meta"]["skills_manifest"]["results"]
))
check("all six skill ids are present", len(r["meta"]["skills_manifest"]["all_skills"]) == 6)
```

只有在服务 `/healthz` 报告 `data_mode=panda` 且 `skill_mode=cli` 时执行“没有 mock”断言；本地离线检查仍允许 mock。

- [ ] **Step 6: 写真实运行说明并执行一次真实检查**

`docs/LIVE_INTEGRATION.md` 写出准确顺序：

```text
python3.12 -m venv .venv-real
.venv-real/bin/pip install -r requirements-real.txt
cp .env.example .env
./scripts/fetch_quantskills.sh
.venv-real/bin/python scripts/setup_real.py --check
DATA_MODE=panda .venv-real/bin/python scripts/warm_cache.py
DATA_MODE=panda SKILL_MODE=cli .venv-real/bin/python scripts/precompute_research.py
RUN_LIVE_INTEGRATION=1 .venv-real/bin/python -m pytest tests/test_live_integration.py -v
```

填 `.env` 时人工写入活动凭证，不能把值复制进文档、shell 历史示例或提交记录。

Run: `RUN_LIVE_INTEGRATION=1 .venv-real/bin/python -m pytest tests/test_live_integration.py -v`

Expected: DeepSeek、PandaData、六个 Skill 和三个完整请求全部 PASS；不足结果允许出现在确实缺字段的 Skill 中，但不能出现 `mock`。

- [ ] **Step 7: 提交测试和脚本，不提交真实记录目录**

```bash
git add tests/test_live_integration.py scripts/setup_real.py scripts/warm_cache.py scripts/smoke_a2a.py scripts/record_live_examples.py docs/LIVE_INTEGRATION.md .gitignore
git commit -m "test: verify live PandaAI integrations"
```

### Task 10: 准备持续在线的 Linux 部署

**Files:**
- Create: `deploy/systemd/devils-committee.service`
- Create: `deploy/nginx/devils-committee.conf.template`
- Create: `scripts/render_nginx_config.sh`
- Create: `scripts/deploy_check.sh`
- Create: `tests/test_deploy_assets.py`

- [ ] **Step 1: 写部署文件失败测试**

创建 `tests/test_deploy_assets.py`：

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_systemd_service_uses_python_312_environment_and_restart():
    text = (ROOT / "deploy/systemd/devils-committee.service").read_text(encoding="utf-8")
    assert "/opt/devils-committee/.venv-real/bin/uvicorn" in text
    assert "EnvironmentFile=/etc/devils-committee/devils-committee.env" in text
    assert "Restart=always" in text
    assert "User=devils" in text


def test_nginx_template_proxies_all_public_routes_without_embedded_secrets():
    text = (ROOT / "deploy/nginx/devils-committee.conf.template").read_text(encoding="utf-8")
    assert "${PUBLIC_HOST}" in text
    assert "proxy_pass http://127.0.0.1:18080" in text
    assert "proxy_buffering off" in text
    assert "Authorization" not in text
    assert "LLM_API_KEY" not in text
```

- [ ] **Step 2: 运行测试，确认部署文件尚不存在**

Run: `.venv/bin/python -m pytest tests/test_deploy_assets.py -v`

Expected: FAIL with `FileNotFoundError`。

- [ ] **Step 3: 创建 systemd 服务**

`deploy/systemd/devils-committee.service`：

```ini
[Unit]
Description=Devil's Committee A2A Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=devils
Group=devils
WorkingDirectory=/opt/devils-committee
EnvironmentFile=/etc/devils-committee/devils-committee.env
Environment=CACHE_DIR=/var/lib/devils-committee/cache
Environment=PRECOMPUTED_DIR=/var/lib/devils-committee/precomputed
ExecStart=/opt/devils-committee/.venv-real/bin/uvicorn backend.a2a_server:app --host 127.0.0.1 --port 18080 --workers 1
Restart=always
RestartSec=5
TimeoutStartSec=60
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/devils-committee

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: 创建 HTTPS 反向代理模板和渲染脚本**

`deploy/nginx/devils-committee.conf.template`：

```nginx
server {
    listen 443 ssl http2;
    server_name ${PUBLIC_HOST};

    ssl_certificate /etc/letsencrypt/live/${PUBLIC_HOST}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${PUBLIC_HOST}/privkey.pem;

    client_max_body_size 2m;
    proxy_read_timeout 610s;
    proxy_send_timeout 610s;

    location / {
        proxy_pass http://127.0.0.1:18080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_buffering off;
    }
}

server {
    listen 80;
    server_name ${PUBLIC_HOST};
    return 301 https://$host$request_uri;
}
```

`scripts/render_nginx_config.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${PUBLIC_HOST:?set PUBLIC_HOST to the deployed hostname}"
case "$PUBLIC_HOST" in
  *[!A-Za-z0-9.-]*|.*|*.) echo "invalid PUBLIC_HOST" >&2; exit 2 ;;
esac
envsubst '${PUBLIC_HOST}' \
  < deploy/nginx/devils-committee.conf.template \
  > "${OUTPUT_PATH:-/tmp/devils-committee.nginx.conf}"
```

生产机安装配置时，把渲染结果复制到 `/etc/nginx/conf.d/devils-committee.conf`，再执行 `sudo nginx -t && sudo systemctl reload nginx`。证书使用主机已有的 Let's Encrypt 流程，不能提交私钥。

- [ ] **Step 5: 创建部署后的只读检查脚本**

`scripts/deploy_check.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${PUBLIC_URL:?set PUBLIC_URL}"
python3 scripts/smoke_a2a.py \
  --url "$PUBLIC_URL" \
  --token "${A2A_BEARER_TOKEN:-}" \
  --ticker "600519.SH 多空证据和风险"
curl --fail --silent --show-error "$PUBLIC_URL/healthz" >/dev/null
curl --fail --silent --show-error "$PUBLIC_URL/.well-known/agent-card.json" >/dev/null
```

- [ ] **Step 6: 运行部署文件测试**

Run: `.venv/bin/python -m pytest tests/test_deploy_assets.py -v && bash -n scripts/render_nginx_config.sh scripts/deploy_check.sh`

Expected: PASS。

- [ ] **Step 7: 在选定主机安装并验证**

在主机创建独立用户、目录和环境文件：

```bash
sudo install -d -o devils -g devils /opt/devils-committee /var/lib/devils-committee/cache /var/lib/devils-committee/precomputed
sudo install -d -m 0750 /etc/devils-committee
sudo install -m 0644 deploy/systemd/devils-committee.service /etc/systemd/system/devils-committee.service
sudo systemctl daemon-reload
sudo systemctl enable --now devils-committee
sudo systemctl status devils-committee --no-pager
```

`/etc/devils-committee/devils-committee.env` 权限设为 `0600`，由主机管理员填写真实凭证。安装 Nginx 配置和证书后运行 `scripts/deploy_check.sh`。若尚未选定主机，完成部署文件和本地测试后停止在这里，不自行使用其他服务器。

- [ ] **Step 8: 提交部署文件**

```bash
git add deploy scripts/render_nginx_config.sh scripts/deploy_check.sh tests/test_deploy_assets.py
git commit -m "ops: add persistent A2A deployment assets"
```

### Task 11: 更新文档、清理旧叙述并完成验收

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/SUBMISSION_18.md`
- Modify: `docs/SUBMISSION_15.md`
- Modify: `docs/SUBMISSION_04_qoder.md`
- Modify: `docs/SUBMISSION_05_teen.md`
- Modify: `docs/SUBMISSION_07_xhs.md`
- Modify: `docs/demo_script.md`
- Modify: `docs/demo_cheatsheet.md`
- Modify: `docs/service_checklist.md`
- Modify: `scripts/gen_submission.py`
- Modify: `scripts/gen_submission_15.py`

- [ ] **Step 1: 更新项目说明和运行命令**

`README.md` 和 `AGENTS.md` 必须明确：

```text
- 默认开发环境可使用 mock；真实环境固定 Python 3.12。
- 真实环境安装 requirements-real.txt。
- 火山方舟模型显示名为 DeepSeek V4 Pro，模型字段填写活动 Endpoint ID。
- 当前真实研究只支持 A 股；港股和美股返回 insufficient-evidence。
- 四个 QuantSkills 每次请求运行，两个 QuantSkills 提前计算。
- live、cache、precomputed、mock 和 insufficient-evidence 的含义不同。
- 不提供买卖指令、目标价、收益承诺或自动交易。
```

`AGENTS.md` 的开发命令改为 Python 3.12，并增加：

```bash
python3.12 -m venv .venv-real
.venv-real/bin/pip install -r requirements-real.txt
./scripts/fetch_quantskills.sh
.venv-real/bin/python scripts/setup_real.py --check
```

- [ ] **Step 2: 更新参评材料中的技术事实**

`docs/SUBMISSION_18.md`、`docs/SUBMISSION_15.md`、`docs/SUBMISSION_05_teen.md`、`docs/SUBMISSION_07_xhs.md`、`docs/ARCHITECTURE.md` 和两个生成脚本改为列出六个真实 Skill、三个 A 股示例、10 分钟内部限制、120 秒单 Skill 限制和真实失败规则。

Qoder 文档只回答项目问题、目标用户和人机分工；截图或录屏继续标为可选材料。真人试用、帖子链接、团队姓名、公网地址和视频链接仍标为“需人工填写”，不得写成已完成。

- [ ] **Step 3: 删除运行代码中的旧地址、旧示例和技术占位文字**

Run:

```bash
rg -n "api\.deepseek\.com|deepseek-chat|AAPL|NVDA|TSLA|real-cli|mock-fallback|real-quant" backend scripts tests web agent-card.json README.md docs/ARCHITECTURE.md docs/SUBMISSION_18.md docs/demo_script.md docs/demo_cheatsheet.md
```

Expected: 无匹配。若文档需要说明“当前不支持美股”，只可在专门的支持范围段落保留一般性文字，不保留美股代码示例。

Run:

```bash
rg -n "confirm exact|wire fully|align exact fields|needs Feishu creds" backend scripts agent-card.json
```

Expected: 无匹配；所有技术接口都已有明确实现或明确返回证据不足。

- [ ] **Step 4: 执行默认测试**

Run: `.venv/bin/python -m pytest -q`

Expected: 0 failed；真实联调测试为 skipped，其余测试通过。

Run: `./scripts/test_frontend.sh`

Expected: 0 failed。

Run: `.venv/bin/python -m compileall -q backend scripts`

Expected: exit 0。

- [ ] **Step 5: 检查格式、凭证和意外提交的数据**

Run:

```bash
git diff --check
git status --short
git grep -nE 'LLM_API_KEY=.+|DEFAULT_PASSWORD=.+|A2A_BEARER_TOKEN=.+' -- ':!.env.example'
git ls-files 'var/*' '.env' 'vendor/*' '*.parquet'
```

Expected: `git diff --check` 无输出；凭证搜索无输出；Git 未跟踪 `.env`、`var/`、`vendor/` 或 Parquet 文件。

- [ ] **Step 6: 使用本地服务做完整检查**

Run:

```bash
.venv/bin/uvicorn backend.a2a_server:app --host 127.0.0.1 --port 8080
```

在另一个终端运行：

```bash
.venv/bin/python scripts/smoke_a2a.py --url http://127.0.0.1:8080 --ticker "600519.SH 多空证据和风险"
```

Expected: health、Agent Card、A2A JSON、`audit_claims` 和 SSE 全部 PASS；默认 mock 环境的模式标记准确。

- [ ] **Step 7: 使用公网地址做最终检查**

Run:

```bash
.venv-real/bin/python scripts/smoke_a2a.py --url "$PUBLIC_URL" --token "$A2A_BEARER_TOKEN" --ticker "600519.SH 多空证据和风险"
```

Expected: 全部 PASS；真实结果中没有 `mock`，总耗时不超过 600 秒，Agent Card URL 与服务地址一致。

- [ ] **Step 8: 提交文档并推送私人仓库**

```bash
git add README.md AGENTS.md docs scripts/gen_submission.py scripts/gen_submission_15.py
git commit -m "docs: describe verified PandaAI integration"
if git show-ref --verify --quiet refs/tags/adventurex2026; then
  test "$(git rev-list -n 1 adventurex2026)" = "$(git rev-parse HEAD)"
else
  git tag adventurex2026
fi
gh repo edit serein431/devils-committee --add-topic adventurex2026
git push origin main
git push origin adventurex2026
```

推送前先用 `git remote -v` 确认目标仍是 `serein431/devils-committee`。私人仓库需要在提交前给评审账号访问权限；如果主办方没有提供账号，则按官方要求准备邮件交付完整代码。

## 需求覆盖核对

| 已确认要求 | 对应任务 |
|---|---|
| 火山方舟 DeepSeek V4 Pro 与凭证脱敏 | Task 1、6、9 |
| PandaData 扩展数据、Parquet 缓存和失败不转 mock | Task 3 |
| 四个在线 QuantSkills、120 秒限制 | Task 4、7 |
| 两个提前计算 QuantSkills、提交号和数据哈希检查 | Task 5 |
| 每条论据引用 Skill、来源状态和文件哈希 | Task 6、7 |
| A 股完整支持，港股和美股返回证据不足 | Task 2、7、8 |
| 三个可重复的 A 股示例 | Task 8、9 |
| A2A、SSE、鉴权、错误脱敏和 10 分钟限制 | Task 7、8、9 |
| 持续在线、HTTPS、进程自动重启和独立缓存目录 | Task 10 |
| 文档、演示、真人试用和社区材料准确区分完成状态 | Task 11 |
