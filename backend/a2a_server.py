"""A2A Remote Agent server with FastAPI, JSON responses, and SSE streaming.

Endpoints:
  GET  /.well-known/agent-card.json   -> the Agent Card (url injected from PUBLIC_URL)
  GET  /healthz                       -> health check
  POST /a2a                            -> A2A message endpoint; JSON or SSE streaming
  GET  /                               -> the coach frontend

Run:  uvicorn backend.a2a_server:app --host 0.0.0.0 --port 8080
Set PUBLIC_URL to the deployed HTTPS address so the Agent Card uses that URL.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hmac
import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .config import CONFIG
from .orchestration import DebateOrchestrator, _extract_symbol
from .research_request import ResearchRequest

log = logging.getLogger("devils-committee")

ROOT = Path(__file__).resolve().parent
CARD_PATH = ROOT / "agent-card.json"
if not CARD_PATH.exists():                      # card lives at repo root in this layout
    CARD_PATH = ROOT.parent / "agent-card.json"
WEB_INDEX = ROOT.parent / "web" / "index.html"
WEB_ASSETS = ROOT.parent / "web" / "assets"

app = FastAPI(title="Devil's Committee A2A", version="1.0.1")
app.mount("/assets", StaticFiles(directory=WEB_ASSETS), name="assets")

_TASKS: dict[str, dict[str, Any]] = {}
_TASK_RUNNERS: dict[str, asyncio.Task] = {}
_TASK_SUBSCRIBERS: dict[str, set[asyncio.Queue]] = {}
_TERMINAL_STATES = {
    "TASK_STATE_COMPLETED",
    "TASK_STATE_FAILED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_REJECTED",
}
_V1_METHODS = {
    "SendMessage",
    "SendStreamingMessage",
    "GetTask",
    "CancelTask",
    "SubscribeToTask",
}
_LEGACY_METHODS = {"message/send", "message/stream"}


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
    card.pop("url", None)
    card["supportedInterfaces"] = [{
        "url": f"{CONFIG.public_url.rstrip('/')}/a2a",
        "protocolBinding": "JSONRPC",
        "protocolVersion": "1.0",
    }]
    card["documentationUrl"] = (
        f"{CONFIG.repository_url.rstrip('/')}/blob/main/README.md"
    )
    card.pop("security", None)
    if CONFIG.bearer_token:
        card["securitySchemes"] = {
            "bearer": {"httpAuthSecurityScheme": {"scheme": "Bearer"}}
        }
        card["securityRequirements"] = [
            {"schemes": {"bearer": {"list": []}}}
        ]
    else:
        card.pop("securitySchemes", None)
        card.pop("securityRequirements", None)
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
    for message in (
        body.get("message"),
        body.get("params", {}).get("message") if isinstance(body.get("params"), dict) else None,
    ):
        parts = message.get("parts") if isinstance(message, dict) else None
        if isinstance(parts, list):
            texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
            joined = " ".join(text for text in texts if text)
            if joined.strip():
                return joined
    return ""


def extract_research_request(body: dict) -> ResearchRequest:
    """Preserve structured research fields while accepting common A2A text shapes."""

    params = body.get("params")
    payload = dict(params) if _is_jsonrpc(body) and isinstance(params, dict) else dict(body)
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            payload.setdefault(key, value)
    topic = extract_topic(body)
    if topic and not payload.get("topic"):
        payload["topic"] = topic
    return ResearchRequest.from_payload(payload)


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _is_jsonrpc(body: dict) -> bool:
    request_id = body.get("id")
    return (
        body.get("jsonrpc") == "2.0"
        and isinstance(request_id, (str, int))
        and not isinstance(request_id, bool)
    )


def _jsonrpc_result(request_id: str | int, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: str | int | None, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _legacy_agent_message(payload: dict) -> dict:
    return {
        "kind": "message",
        "role": "agent",
        "messageId": str(uuid4()),
        "parts": [{"kind": "text", "text": json.dumps(payload, ensure_ascii=False)}],
    }


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _v1_agent_message(
    text: str,
    *,
    context_id: str,
    task_id: str,
) -> dict:
    return {
        "messageId": str(uuid4()),
        "contextId": context_id,
        "taskId": task_id,
        "role": "ROLE_AGENT",
        "parts": [{"text": text}],
    }


def _task_status(
    state: str,
    *,
    context_id: str,
    task_id: str,
    text: str,
) -> dict:
    return {
        "state": state,
        "message": _v1_agent_message(text, context_id=context_id, task_id=task_id),
        "timestamp": _timestamp(),
    }


def _normalise_user_message(message: dict, *, context_id: str, task_id: str) -> dict:
    normalised = deepcopy(message)
    normalised["contextId"] = context_id
    normalised["taskId"] = task_id
    return normalised


def _new_task(message: dict, *, skill: str) -> dict:
    task_id = str(uuid4())
    context_id = message.get("contextId") or str(uuid4())
    task = {
        "id": task_id,
        "contextId": context_id,
        "status": _task_status(
            "TASK_STATE_SUBMITTED",
            context_id=context_id,
            task_id=task_id,
            text="研究任务已提交。",
        ),
        "artifacts": [],
        "history": [
            _normalise_user_message(message, context_id=context_id, task_id=task_id)
        ],
        "metadata": {"skill": skill},
    }
    _TASKS[task_id] = task
    return task


def _task_snapshot(task_id: str, history_length: int | None = None) -> dict:
    task = deepcopy(_TASKS[task_id])
    if history_length is not None:
        task["history"] = [] if history_length == 0 else task["history"][-history_length:]
    return task


def _notify_subscribers(task_id: str, event: dict) -> None:
    for queue in tuple(_TASK_SUBSCRIBERS.get(task_id, ())):
        queue.put_nowait(deepcopy(event))


def _set_task_status(task_id: str, state: str, text: str) -> dict:
    task = _TASKS[task_id]
    status = _task_status(
        state,
        context_id=task["contextId"],
        task_id=task_id,
        text=text,
    )
    task["status"] = status
    update = {
        "taskId": task_id,
        "contextId": task["contextId"],
        "status": deepcopy(status),
    }
    _notify_subscribers(task_id, {"statusUpdate": update})
    return update


def _result_artifact(task_id: str, payload: dict, *, skill: str) -> dict:
    return {
        "artifactId": f"research-result-{task_id}",
        "name": "research-result",
        "description": "Devil's Committee research and audit result",
        "parts": [{"data": payload, "mediaType": "application/json"}],
        "metadata": {"skill": skill},
    }


def _complete_task(task_id: str, payload: dict, *, skill: str) -> tuple[dict, dict]:
    task = _TASKS[task_id]
    artifact = _result_artifact(task_id, payload, skill=skill)
    task["artifacts"] = [artifact]
    task["history"].append(
        _v1_agent_message(
            "研究完成，结构化结果已写入 artifacts。",
            context_id=task["contextId"],
            task_id=task_id,
        )
    )
    artifact_update = {
        "taskId": task_id,
        "contextId": task["contextId"],
        "artifact": deepcopy(artifact),
        "append": False,
        "lastChunk": True,
    }
    _notify_subscribers(task_id, {"artifactUpdate": artifact_update})
    status_update = _set_task_status(task_id, "TASK_STATE_COMPLETED", "研究任务已完成。")
    return artifact_update, status_update


def _fail_task(task_id: str) -> dict:
    return _set_task_status(task_id, "TASK_STATE_FAILED", "研究任务执行失败。")


def _cancel_task(task_id: str) -> dict:
    return _set_task_status(task_id, "TASK_STATE_CANCELED", "研究任务已取消。")


def _valid_v1_message(message: Any) -> bool:
    if not isinstance(message, dict):
        return False
    if not isinstance(message.get("messageId"), str) or not message["messageId"].strip():
        return False
    if message.get("role") != "ROLE_USER":
        return False
    parts = message.get("parts")
    return (
        isinstance(parts, list)
        and bool(parts)
        and all(
            isinstance(part, dict)
            and any(key in part for key in ("text", "data", "url", "raw"))
            for part in parts
        )
    )


def _v1_skill(params: dict) -> str:
    metadata = params.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("skill"), str):
        return metadata["skill"]
    return params.get("skill", "debate_case")


def _configuration_history_length(params: dict) -> tuple[int | None, bool]:
    configuration = params.get("configuration")
    if configuration is None:
        return None, True
    if not isinstance(configuration, dict):
        return None, False
    history_length = configuration.get("historyLength")
    if history_length is None:
        return None, True
    if (
        not isinstance(history_length, int)
        or isinstance(history_length, bool)
        or history_length < 0
    ):
        return None, False
    return history_length, True


def _task_for_message(
    message: dict,
    *,
    skill: str,
) -> tuple[dict | None, tuple[int, str] | None]:
    task_id = message.get("taskId")
    if task_id is None:
        return _new_task(message, skill=skill), None
    if not isinstance(task_id, str) or not task_id:
        return None, (-32602, "Invalid params")
    task = _TASKS.get(task_id)
    if task is None:
        return None, (-32001, "Task not found")
    context_id = message.get("contextId")
    if not isinstance(context_id, str) or context_id != task["contextId"]:
        return None, (-32602, "Invalid params")
    task["history"].append(
        _normalise_user_message(
            message,
            context_id=context_id,
            task_id=task_id,
        )
    )
    task["artifacts"] = []
    task["metadata"] = {"skill": skill}
    _set_task_status(task_id, "TASK_STATE_SUBMITTED", "研究任务已提交。")
    return task, None


def _progress_text(event: dict) -> str | None:
    stage = event.get("stage")
    if stage == "data":
        return event.get("msg") or "正在读取 PandaData 研究数据。"
    if stage == "skills":
        return event.get("msg") or "正在运行金融 Skills。"
    if stage == "argue":
        return event.get("msg") or "四个研究 Agent 正在分析同一批证据。"
    if stage == "rebut":
        return event.get("msg") or "四个研究 Agent 正在交叉质询首轮论据。"
    if stage == "claim_start":
        name = event.get("agent") or event.get("side") or "研究 Agent"
        action = "开始回应对方论据" if event.get("kind") == "rebuttal" else "开始陈述"
        return f"{name} {action}。"
    if stage == "audit":
        return event.get("msg") or "审计 Agent 正在核查证据。"
    if stage == "synthesize":
        return event.get("msg") or "主持 Agent 正在汇总分歧。"
    return None


async def _run_v1_task(
    task_id: str,
    research_request: ResearchRequest,
    *,
    skill: str,
) -> None:
    try:
        _set_task_status(task_id, "TASK_STATE_WORKING", "正在读取数据并执行研究。")
        orchestrator = DebateOrchestrator()
        if skill == "audit_claims":
            payload = await orchestrator.audit_claims(research_request)
        else:
            payload = (await orchestrator.run(research_request)).to_dict()
        if _TASKS[task_id]["status"]["state"] != "TASK_STATE_CANCELED":
            _complete_task(task_id, payload, skill=skill)
    except asyncio.CancelledError:
        if _TASKS[task_id]["status"]["state"] != "TASK_STATE_CANCELED":
            _cancel_task(task_id)
    except Exception:
        log.exception("A2A v1 task failed")
        _fail_task(task_id)
    finally:
        _TASK_RUNNERS.pop(task_id, None)


async def _run_v1_streaming_task(
    task_id: str,
    research_request: ResearchRequest,
    *,
    skill: str,
    queue: asyncio.Queue,
) -> None:
    try:
        working = _set_task_status(
            task_id,
            "TASK_STATE_WORKING",
            "正在读取 PandaData 并运行金融 Skills。",
        )
        await queue.put({"statusUpdate": working})
        orchestrator = DebateOrchestrator()
        payload = None
        if skill == "audit_claims":
            payload = await orchestrator.audit_claims(research_request)
        else:
            async for event in orchestrator.stream(research_request, pace=0):
                if event.get("stage") == "result":
                    payload = event.get("result")
                    continue
                progress = _progress_text(event)
                if progress:
                    update = _set_task_status(task_id, "TASK_STATE_WORKING", progress)
                    update["metadata"] = {"stage": event.get("stage")}
                    await queue.put({"statusUpdate": update})
        if not isinstance(payload, dict):
            raise RuntimeError("task produced no result")
        if _TASKS[task_id]["status"]["state"] != "TASK_STATE_CANCELED":
            artifact_update, status_update = _complete_task(task_id, payload, skill=skill)
            await queue.put({"artifactUpdate": artifact_update})
            await queue.put({"statusUpdate": status_update})
    except asyncio.CancelledError:
        task = _TASKS[task_id]
        if task["status"]["state"] != "TASK_STATE_CANCELED":
            canceled = _cancel_task(task_id)
        else:
            canceled = {
                "taskId": task_id,
                "contextId": task["contextId"],
                "status": deepcopy(task["status"]),
            }
        await queue.put({"statusUpdate": canceled})
    except Exception:
        log.exception("A2A v1 streaming task failed")
        failed = _fail_task(task_id)
        await queue.put({"statusUpdate": failed})
    finally:
        _TASK_RUNNERS.pop(task_id, None)
        await queue.put(None)


def _v1_error(request_id: str | int | None, code: int, message: str) -> JSONResponse:
    return JSONResponse(_jsonrpc_error(request_id, code, message))


async def _handle_v1(body: dict) -> JSONResponse | StreamingResponse:
    request_id = body.get("id")
    method = body.get("method")
    params = body.get("params")
    if not isinstance(params, dict):
        return _v1_error(request_id, -32602, "Invalid params")

    if method == "GetTask":
        task_id = params.get("id")
        if not isinstance(task_id, str) or not task_id:
            return _v1_error(request_id, -32602, "Invalid params")
        if task_id not in _TASKS:
            return _v1_error(request_id, -32001, "Task not found")
        history_length = params.get("historyLength")
        if history_length is not None and (
            not isinstance(history_length, int) or history_length < 0
        ):
            return _v1_error(request_id, -32602, "Invalid params")
        return JSONResponse(
            _jsonrpc_result(request_id, _task_snapshot(task_id, history_length))
        )

    if method == "CancelTask":
        task_id = params.get("id")
        if not isinstance(task_id, str) or not task_id:
            return _v1_error(request_id, -32602, "Invalid params")
        if task_id not in _TASKS:
            return _v1_error(request_id, -32001, "Task not found")
        if _TASKS[task_id]["status"]["state"] in _TERMINAL_STATES:
            return _v1_error(request_id, -32002, "Task not cancelable")
        _cancel_task(task_id)
        runner = _TASK_RUNNERS.get(task_id)
        if runner is not None:
            runner.cancel()
        return JSONResponse(_jsonrpc_result(request_id, _task_snapshot(task_id)))

    if method == "SubscribeToTask":
        task_id = params.get("id")
        if not isinstance(task_id, str) or not task_id:
            return _v1_error(request_id, -32602, "Invalid params")
        task = _TASKS.get(task_id)
        if task is None:
            return _v1_error(request_id, -32001, "Task not found")
        if task["status"]["state"] in _TERMINAL_STATES:
            return _v1_error(request_id, -32004, "Task not subscribable")

        queue: asyncio.Queue = asyncio.Queue()
        _TASK_SUBSCRIBERS.setdefault(task_id, set()).add(queue)
        initial_update = {
            "statusUpdate": {
                "taskId": task_id,
                "contextId": task["contextId"],
                "status": deepcopy(task["status"]),
            }
        }

        async def subscribe_v1():
            try:
                yield _sse(_jsonrpc_result(request_id, initial_update))
                while True:
                    event = await queue.get()
                    yield _sse(_jsonrpc_result(request_id, event))
                    status_update = event.get("statusUpdate")
                    if (
                        isinstance(status_update, dict)
                        and status_update.get("status", {}).get("state")
                        in _TERMINAL_STATES
                    ):
                        break
            finally:
                subscribers = _TASK_SUBSCRIBERS.get(task_id)
                if subscribers is not None:
                    subscribers.discard(queue)
                    if not subscribers:
                        _TASK_SUBSCRIBERS.pop(task_id, None)

        return StreamingResponse(
            subscribe_v1(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    message = params.get("message")
    if not _valid_v1_message(message):
        return _v1_error(request_id, -32602, "Invalid params")
    try:
        research_request = extract_research_request(body)
    except (TypeError, ValueError):
        return _v1_error(request_id, -32602, "Invalid params")
    if not research_request.question:
        return _v1_error(request_id, -32602, "Invalid params")

    history_length, valid_configuration = _configuration_history_length(params)
    if not valid_configuration:
        return _v1_error(request_id, -32602, "Invalid params")

    skill = _v1_skill(params)
    task, task_error = _task_for_message(message, skill=skill)
    if task_error is not None:
        return _v1_error(request_id, *task_error)
    assert task is not None
    task_id = task["id"]

    if method == "SendMessage":
        configuration = params.get("configuration")
        return_immediately = (
            isinstance(configuration, dict)
            and configuration.get("returnImmediately") is True
        )
        initial = _task_snapshot(task_id, history_length)
        runner = asyncio.create_task(
            _run_v1_task(task_id, research_request, skill=skill)
        )
        _TASK_RUNNERS[task_id] = runner
        if return_immediately:
            return JSONResponse(_jsonrpc_result(request_id, {"task": initial}))
        await runner
        return JSONResponse(
            _jsonrpc_result(
                request_id,
                {"task": _task_snapshot(task_id, history_length)},
            )
        )

    queue: asyncio.Queue = asyncio.Queue()
    initial = _task_snapshot(task_id, history_length)

    async def stream_v1():
        runner = asyncio.create_task(
            _run_v1_streaming_task(
                task_id,
                research_request,
                skill=skill,
                queue=queue,
            )
        )
        _TASK_RUNNERS[task_id] = runner
        yield _sse(_jsonrpc_result(request_id, {"task": initial}))
        while True:
            event = await queue.get()
            if event is None:
                break
            yield _sse(_jsonrpc_result(request_id, event))

    return StreamingResponse(
        stream_v1(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/a2a")
async def a2a(
    request: Request,
    authorization: str | None = Header(default=None),
    a2a_version: str | None = Header(default=None, alias="A2A-Version"),
):
    _check_auth(authorization)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("request body must be an object")
    except (TypeError, ValueError, json.JSONDecodeError):
        query_topic = (request.query_params.get("topic") or "").strip()
        if not query_topic:
            return JSONResponse(status_code=422, content={"detail": "invalid request"})
        body = {
            "topic": query_topic,
            "skill": request.query_params.get("skill") or "debate_case",
        }
    jsonrpc = _is_jsonrpc(body)
    request_id = body.get("id") if jsonrpc else None
    method = body.get("method") if jsonrpc else None
    protocol_version = a2a_version.strip() if a2a_version else None
    if protocol_version not in {None, "0.3", "1.0"}:
        return JSONResponse(
            _jsonrpc_error(request_id, -32009, "Version not supported")
        )
    if jsonrpc:
        if protocol_version == "1.0":
            if method in _V1_METHODS:
                return await _handle_v1(body)
            return JSONResponse(
                _jsonrpc_error(request_id, -32601, "method not found")
            )
        if method not in _LEGACY_METHODS:
            return JSONResponse(
                _jsonrpc_error(request_id, -32601, "method not found")
            )
    try:
        research_request = extract_research_request(body)
    except (TypeError, ValueError):
        if jsonrpc:
            return JSONResponse(_jsonrpc_error(request_id, -32602, "invalid params"))
        return JSONResponse(status_code=422, content={"detail": "invalid request"})
    if not research_request.question:
        if jsonrpc:
            return JSONResponse(_jsonrpc_error(request_id, -32602, "no task/topic found in message"))
        raise HTTPException(status_code=422, detail="no task/topic found in message")

    wants_stream = (
        (jsonrpc and method == "message/stream")
        or "text/event-stream" in (request.headers.get("accept") or "")
        or request.query_params.get("stream") in ("1", "true")
        or bool(body.get("stream"))
    )

    params = body.get("params") if jsonrpc else None
    skill = (params or {}).get("skill", "debate_case") if isinstance(params, dict) else body.get("skill", "debate_case")

    # Second advertised skill on the Agent Card — must actually work when called.
    if skill == "audit_claims":
        if jsonrpc and wants_stream:
            async def audit_stream():
                try:
                    result = await DebateOrchestrator().audit_claims(research_request)
                    yield _sse(_jsonrpc_result(request_id, _legacy_agent_message(result)))
                except Exception:
                    log.exception("JSON-RPC audit stream failed")
                    yield _sse(_jsonrpc_error(request_id, -32603, "internal error"))

            return StreamingResponse(
                audit_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        try:
            result = await DebateOrchestrator().audit_claims(research_request)
        except Exception:
            log.exception("audit_claims failed")   # detail stays in server logs, not response
            if jsonrpc:
                return JSONResponse(_jsonrpc_error(request_id, -32603, "internal error"))
            return JSONResponse(status_code=500,
                                content={"skill": "audit_claims", "error": "internal error"})
        if jsonrpc:
            return JSONResponse(_jsonrpc_result(request_id, _legacy_agent_message(result)))
        return JSONResponse({"skill": "audit_claims", "result": result})

    if not wants_stream:
        try:
            result = await DebateOrchestrator().run(research_request)
        except Exception:                        # never leak internals to the A2A caller
            log.exception("debate failed")
            if jsonrpc:
                return JSONResponse(_jsonrpc_error(request_id, -32603, "internal error"))
            return JSONResponse(status_code=500,
                                content={"skill": skill, "error": "internal error"})
        if jsonrpc:
            return JSONResponse(_jsonrpc_result(request_id, _legacy_agent_message(result.to_dict())))
        return JSONResponse({"skill": skill, "result": result.to_dict()})

    # Demo pacing: give a live audience the reveal drama; keep A2A-machine calls
    # fast. `pace` overridable via ?pace=; defaults to a gentle 0.35s for humans.
    try:
        pace = float(request.query_params.get("pace", "0.35"))
    except ValueError:
        pace = 0.35

    async def stream():
        if jsonrpc:
            try:
                result = await DebateOrchestrator().run(research_request)
                yield _sse(_jsonrpc_result(request_id, _legacy_agent_message(result.to_dict())))
            except Exception:
                log.exception("JSON-RPC stream failed")
                yield _sse(_jsonrpc_error(request_id, -32603, "internal error"))
            return
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
