"""Local human control-plane dashboard for ContextBridge.

The dashboard is deliberately outside the MCP surface. It may inspect telemetry/evaluations and
approve or reject signed pending actions, but it is never callable as an MCP tool. By default it
binds only to 127.0.0.1. Binding to a non-loopback address requires an explicit dashboard token.
"""
from __future__ import annotations

import argparse
import asyncio
import hmac
import ipaddress
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from contextbridge import __version__
from contextbridge.config import settings
from contextbridge.evaluation import DEFAULT_BENCHMARK, run_and_record
from contextbridge.chat import ChatConfigurationError, ChatProviderError, provider_status, run_chat_turn
from contextbridge.telemetry.instrumentation import get_telemetry_store

STATIC_DIR = Path(__file__).resolve().parent / "dashboard_static"

TOOL_CATALOG = [
    ("server_info", "read", "ContextBridge identity and runtime version."),
    ("health", "read", "Lightweight service health check."),
    ("github_connection_status", "read", "Authenticated GitHub identity and rate-limit state."),
    ("list_repositories", "read", "List repositories visible to the configured credential."),
    ("get_repository", "read", "Read repository metadata."),
    ("search_issues", "read", "Search issues with structured filters."),
    ("get_issue", "read", "Read one issue."),
    ("list_pull_requests", "read", "List pull requests for a repository."),
    ("get_pull_request", "read", "Read one pull request."),
    ("list_commits", "read", "List repository commits."),
    ("get_file_contents", "read", "Read text files or directory listings."),
    ("search_code", "read", "Search code visible to the GitHub credential."),
    ("get_workflow_runs", "read", "Read GitHub Actions workflow runs."),
    ("get_commit_status", "read", "Read combined commit status contexts."),
    ("get_tool_metrics", "read", "Read local success/failure and latency metrics."),
    ("get_recent_tool_calls", "read", "Read recent redacted MCP executions."),
    ("get_audit_summary", "read", "Read immutable audit-stream summary."),
    ("get_write_policy", "read", "Inspect mutation gates and safety configuration."),
    ("list_pending_actions", "read", "List signed human-confirmation actions."),
    ("get_pending_action", "read", "Inspect one signed action."),
    ("execute_approved_action", "destructive", "Consume one human-approved action; dry-run simulates."),
    ("create_issue", "write", "Request issue creation; always enters human approval."),
    ("add_issue_comment", "write", "Request issue comment; always enters human approval."),
    ("add_labels", "write", "Request issue labels; always enters human approval."),
    ("close_issue", "destructive", "Request issue closure; always enters human approval."),
    ("reopen_issue", "write", "Request issue reopening; always enters human approval."),
    ("get_evaluation_summary", "read", "Read latest persisted evaluation result."),
]


class DecisionBody(BaseModel):
    confirmation: str
    reason: str | None = None


class ChatSessionBody(BaseModel):
    title: str | None = None


class ChatTurnBody(BaseModel):
    message: str
    read_only: bool | None = None


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _auth_dependency(x_contextbridge_dashboard_token: str | None = Header(default=None)) -> None:
    configured = settings.dashboard_token
    if not configured:
        return
    if not x_contextbridge_dashboard_token or not hmac.compare_digest(
        configured, x_contextbridge_dashboard_token
    ):
        raise HTTPException(status_code=401, detail="Dashboard token required.")


app = FastAPI(
    title="ContextBridge Control Plane",
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/api/health", dependencies=[Depends(_auth_dependency)])
async def api_health() -> dict[str, Any]:
    store = get_telemetry_store()
    database = await store.database_status()
    return {
        "ok": True,
        "name": settings.name,
        "version": settings.version,
        "environment": settings.environment,
        "dry_run": settings.dry_run,
        "github_writes_enabled": settings.github_writes_enabled,
        "write_repositories": list(settings.github_write_repositories),
        "confirmation_ttl_minutes": settings.confirmation_ttl_minutes,
        "approval_channels": ["local_cli", "local_dashboard"],
        "mcp_approval_available": False,
        "database": database,
        "chat": provider_status(),
    }


@app.get("/api/metrics", dependencies=[Depends(_auth_dependency)])
async def api_metrics(hours: int = Query(default=24, ge=1, le=8760)) -> dict[str, Any]:
    return await get_telemetry_store().metrics(hours=hours)


@app.get("/api/tool-calls", dependencies=[Depends(_auth_dependency)])
async def api_tool_calls(limit: int = Query(default=100, ge=1, le=200)) -> list[dict[str, Any]]:
    return await get_telemetry_store().recent_tool_calls(limit=limit)


@app.get("/api/audit", dependencies=[Depends(_auth_dependency)])
async def api_audit(limit: int = Query(default=100, ge=1, le=100)) -> dict[str, Any]:
    return await get_telemetry_store().audit_summary(hours=None, recent_limit=limit)


@app.get("/api/actions", dependencies=[Depends(_auth_dependency)])
async def api_actions(
    status: str | None = None, limit: int = Query(default=100, ge=1, le=200)
) -> list[dict[str, Any]]:
    return await get_telemetry_store().list_pending_actions(status=status, limit=limit)


@app.get("/api/actions/{action_id}", dependencies=[Depends(_auth_dependency)])
async def api_action(action_id: str) -> dict[str, Any]:
    item = await get_telemetry_store().get_pending_action(action_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Action not found.")
    return item


async def _decide(action_id: str, body: DecisionBody, *, approve: bool) -> dict[str, Any]:
    expected = "APPROVE" if approve else "REJECT"
    if body.confirmation.strip() != expected:
        raise HTTPException(status_code=400, detail=f"Type {expected} exactly to confirm this decision.")
    result = await get_telemetry_store().decide_pending_action(
        action_id=action_id,
        approve=approve,
        actor="human:local_dashboard",
        reason=body.reason,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error", {}).get("message", "Decision refused."))
    return result


@app.post("/api/actions/{action_id}/approve", dependencies=[Depends(_auth_dependency)])
async def api_approve(action_id: str, body: DecisionBody) -> dict[str, Any]:
    return await _decide(action_id, body, approve=True)


@app.post("/api/actions/{action_id}/reject", dependencies=[Depends(_auth_dependency)])
async def api_reject(action_id: str, body: DecisionBody) -> dict[str, Any]:
    return await _decide(action_id, body, approve=False)


@app.get("/api/tools", dependencies=[Depends(_auth_dependency)])
async def api_tools() -> list[dict[str, Any]]:
    mutating = {"execute_approved_action", "create_issue", "add_issue_comment", "add_labels", "close_issue", "reopen_issue"}
    return [
        {
            "name": name,
            "risk": risk,
            "description": description,
            "human_confirmation": name in mutating,
        }
        for name, risk, description in TOOL_CATALOG
    ]


@app.get("/api/evaluations", dependencies=[Depends(_auth_dependency)])
async def api_evaluation_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
    return await get_telemetry_store().list_evaluation_runs(limit=limit)


@app.get("/api/evaluations/latest", dependencies=[Depends(_auth_dependency)])
async def api_latest_evaluation() -> dict[str, Any]:
    item = await get_telemetry_store().get_evaluation_run()
    return {"available": item is not None, "evaluation": item}


@app.post("/api/evaluations/baseline", dependencies=[Depends(_auth_dependency)])
async def api_run_baseline() -> dict[str, Any]:
    # Local deterministic benchmark only: no network/model/API call occurs.
    return await run_and_record(benchmark_path=DEFAULT_BENCHMARK, mode="baseline")


@app.get("/api/chat/config", dependencies=[Depends(_auth_dependency)])
async def api_chat_config() -> dict[str, Any]:
    return provider_status()


@app.get("/api/chat/sessions", dependencies=[Depends(_auth_dependency)])
async def api_chat_sessions(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    return await get_telemetry_store().list_chat_sessions(limit=limit)


@app.post("/api/chat/sessions", dependencies=[Depends(_auth_dependency)])
async def api_create_chat_session(body: ChatSessionBody) -> dict[str, Any]:
    status = provider_status()
    return await get_telemetry_store().create_chat_session(
        provider=status["provider"], model=status["model"],
        title=(body.title or "New conversation").strip()[:160] or "New conversation",
    )


@app.get("/api/chat/sessions/{session_id}", dependencies=[Depends(_auth_dependency)])
async def api_chat_session(session_id: str) -> dict[str, Any]:
    store = get_telemetry_store()
    session = await store.get_chat_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return {"session": session, "messages": await store.list_chat_messages(session_id=session_id, limit=200), "tool_calls": await store.list_chat_tool_calls(session_id=session_id, limit=300)}


@app.delete("/api/chat/sessions/{session_id}", dependencies=[Depends(_auth_dependency)])
async def api_delete_chat_session(session_id: str) -> dict[str, Any]:
    deleted = await get_telemetry_store().delete_chat_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return {"ok": True, "deleted": True, "session_id": session_id}


@app.post("/api/chat/sessions/{session_id}/turn", dependencies=[Depends(_auth_dependency)])
async def api_chat_turn(session_id: str, body: ChatTurnBody) -> dict[str, Any]:
    read_only = settings.chat_read_only_default if body.read_only is None else bool(body.read_only)
    try:
        return await run_chat_turn(session_id=session_id, user_message=body.message, read_only=read_only)
    except KeyError:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ChatConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ChatProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/chat/sessions/{session_id}/stream", dependencies=[Depends(_auth_dependency)])
async def api_chat_stream(session_id: str, body: ChatTurnBody) -> StreamingResponse:
    read_only = settings.chat_read_only_default if body.read_only is None else bool(body.read_only)
    async def event_source():
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        async def runner() -> None:
            try:
                await run_chat_turn(session_id=session_id, user_message=body.message, read_only=read_only, event_queue=queue)
            except Exception as exc:
                if queue.empty():
                    await queue.put({"type":"error","message":str(exc)})
            finally:
                await queue.put({"type":"done"})
        task = asyncio.create_task(runner())
        try:
            while True:
                event = await queue.get()
                import json
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                if event.get("type") == "done":
                    break
        finally:
            if not task.done():
                task.cancel()
    return StreamingResponse(event_source(), media_type="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


if STATIC_DIR.is_dir():
    # Registered after all /api routes, so this catch-all never shadows the control-plane API.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="dashboard")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local ContextBridge dashboard")
    parser.add_argument("--host", default=settings.dashboard_host)
    parser.add_argument("--port", type=int, default=settings.dashboard_port)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if not _is_loopback(args.host) and not settings.dashboard_token:
        raise SystemExit(
            "REFUSED: non-loopback dashboard binding requires CONTEXTBRIDGE_DASHBOARD_TOKEN. "
            "Use 127.0.0.1 for local-only access."
        )
    asyncio.run(
        get_telemetry_store().record_system_event(
            kind="dashboard_start",
            status="ok",
            message=f"Local dashboard started on {args.host}:{args.port}.",
            metadata={"host": args.host, "port": args.port, "token_required": bool(settings.dashboard_token)},
        )
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
