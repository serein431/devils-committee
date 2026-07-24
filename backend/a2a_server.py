"""A2A Remote Agent server (track 18 submission form) — FastAPI + SSE.

Endpoints:
  GET  /.well-known/agent-card.json   -> the Agent Card (url injected from PUBLIC_URL)
  GET  /healthz                       -> health check (keep the service ALWAYS ONLINE)
  POST /a2a                            -> A2A message endpoint; JSON or SSE streaming
  GET  /                               -> the coach frontend (track 15)

Run:  uvicorn backend.a2a_server:app --host 0.0.0.0 --port 8080
Host publicly (Cloudflare Tunnel / VPS) and put that URL in PUBLIC_URL + the card.

TODO(feishu): align the /a2a request/response envelope with the official A2A
sample from the PandaAI group and register the URL in their test environment.
`extract_topic` already accepts several common shapes defensively.
"""
from __future__ import annotations

import hmac
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse, PlainTextResponse

from .config import CONFIG
from .orchestration import DebateOrchestrator, _extract_symbol
from .research_request import ResearchRequest

log = logging.getLogger("devils-committee")

ROOT = Path(__file__).resolve().parent
CARD_PATH = ROOT / "agent-card.json"
if not CARD_PATH.exists():                      # card lives at repo root in this layout
    CARD_PATH = ROOT.parent / "agent-card.json"
WEB_INDEX = ROOT.parent / "web" / "index.html"

app = FastAPI(title="Devil's Committee A2A", version="0.2.0")


# --- auth ------------------------------------------------------------------
def _check_auth(authorization: str | None) -> None:
    if not CONFIG.bearer_token:
        return                                  # dev mode: auth disabled
    expected = f"Bearer {CONFIG.bearer_token}"
    # constant-time compare so a wrong token can't be guessed by response timing
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


# --- discovery / health ----------------------------------------------------
@app.get("/.well-known/agent-card.json")
async def agent_card() -> JSONResponse:
    card = json.loads(CARD_PATH.read_text(encoding="utf-8"))
    card["url"] = f"{CONFIG.public_url.rstrip('/')}/a2a"
    card["documentationUrl"] = (
        f"{CONFIG.repository_url.rstrip('/')}/blob/main/README.md"
    )
    return JSONResponse(card)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "service": "devils-committee", "modes": CONFIG.summary()}


# --- A2A message endpoint --------------------------------------------------
def extract_topic(body: dict) -> str:
    """Pull the natural-language task out of several plausible A2A shapes."""
    for path in (
        ("topic",),
        ("params", "message", "text"),
        ("message", "text"),
        ("input",),
        ("question",),
    ):
        cur = body
        ok = True
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                ok = False
                break
        if ok and isinstance(cur, str) and cur.strip():
            return cur
    # A2A parts array: {"message": {"parts": [{"text": "..."}]}}
    parts = body.get("message", {}).get("parts") if isinstance(body.get("message"), dict) else None
    if isinstance(parts, list):
        texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
        joined = " ".join(t for t in texts if t)
        if joined.strip():
            return joined
    return ""


def extract_research_request(body: dict) -> ResearchRequest:
    """Preserve structured research fields while accepting common A2A text shapes."""

    payload = dict(body)
    topic = extract_topic(body)
    if topic and not payload.get("topic"):
        payload["topic"] = topic
    return ResearchRequest.from_payload(payload)


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@app.post("/a2a")
async def a2a(request: Request, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("request body must be an object")
        research_request = extract_research_request(body)
    except (TypeError, ValueError, json.JSONDecodeError):
        return JSONResponse(status_code=422, content={"detail": "invalid request"})
    if not research_request.question:
        raise HTTPException(status_code=422, detail="no task/topic found in message")

    wants_stream = (
        "text/event-stream" in (request.headers.get("accept") or "")
        or request.query_params.get("stream") in ("1", "true")
        or bool(body.get("stream"))
    )

    skill = body.get("skill", "debate_case")

    # Second advertised skill on the Agent Card — must actually work when called.
    if skill == "audit_claims":
        try:
            result = await DebateOrchestrator().audit_claims(research_request)
        except Exception:
            log.exception("audit_claims failed")   # detail stays in server logs, not response
            return JSONResponse(status_code=500,
                                content={"skill": "audit_claims", "error": "internal error"})
        return JSONResponse({"skill": "audit_claims", "result": result})

    if not wants_stream:
        try:
            result = await DebateOrchestrator().run(research_request)
        except Exception:                        # never leak internals to the A2A caller
            log.exception("debate failed")
            return JSONResponse(status_code=500,
                                content={"skill": skill, "error": "internal error"})
        return JSONResponse({"skill": skill, "result": result.to_dict()})

    # Demo pacing: give a live audience the reveal drama; keep A2A-machine calls
    # fast. `pace` overridable via ?pace=; defaults to a gentle 0.35s for humans.
    try:
        pace = float(request.query_params.get("pace", "0.35"))
    except ValueError:
        pace = 0.35

    async def stream():
        orch = DebateOrchestrator()
        try:
            async for ev in orch.stream(research_request, pace=pace):
                yield _sse(ev)
        except Exception:                        # keep the SSE connection well-formed
            log.exception("stream failed")
            yield _sse({"stage": "error", "error": "internal error"})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# --- coach frontend (track 15) --------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    if WEB_INDEX.exists():
        return HTMLResponse(WEB_INDEX.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Devil's Committee</h1><p>web/index.html not found</p>")


def _static_html(rel: str) -> HTMLResponse:
    p = ROOT.parent / rel
    if p.exists():
        return HTMLResponse(p.read_text(encoding="utf-8"))
    return HTMLResponse(f"<h1>not found</h1><p>{rel}</p>", status_code=404)


@app.get("/deck", response_class=HTMLResponse)
async def deck() -> HTMLResponse:            # pitch 幻灯（← → 翻页，F 全屏）
    return _static_html("docs/pitch/deck.html")


@app.get("/whitepaper", response_class=HTMLResponse)
async def whitepaper() -> HTMLResponse:      # 技术白皮书（Cmd/Ctrl+P 导出 PDF）
    return _static_html("docs/WHITEPAPER.html")


@app.get("/research")
async def research_report():                 # real factor-research report (panda mode)
    try:
        from .quant import report as qreport
        return JSONResponse(qreport.full_report())
    except Exception as e:
        return JSONResponse(status_code=503,
                            content={"error": "research needs DATA_MODE=panda", "detail": str(e)[:160]})


@app.get("/symbol/{topic}", response_class=PlainTextResponse)
async def symbol_debug(topic: str) -> str:
    return _extract_symbol(topic)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.a2a_server:app", host=CONFIG.host, port=CONFIG.port, reload=False)
