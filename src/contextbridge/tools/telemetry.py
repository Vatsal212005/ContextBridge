"""Read-only observability tools backed by ContextBridge's local SQLite database."""

from __future__ import annotations

from typing import Any, Literal

from contextbridge.telemetry.instrumentation import get_telemetry_store, observed_tool


@observed_tool(risk_level="read")
async def get_tool_metrics(hours: int = 24, all_time: bool = False) -> dict[str, Any]:
    """Return tool-call success, failure, latency, and per-tool metrics from local telemetry."""
    store = get_telemetry_store()
    metrics = await store.metrics(hours=None if all_time else hours)
    database = await store.database_status()
    return {"ok": True, "metrics": metrics, "database": database}


@observed_tool(risk_level="read")
async def get_recent_tool_calls(
    limit: int = 25,
    tool_name: str | None = None,
    status: Literal["success", "error", "blocked", "confirmation_required"] | None = None,
) -> dict[str, Any]:
    """Return recent local MCP tool executions with redacted arguments and timing/error metadata."""
    store = get_telemetry_store()
    calls = await store.recent_tool_calls(limit=limit, tool_name=tool_name, status=status)
    return {"ok": True, "count": len(calls), "tool_calls": calls}


@observed_tool(risk_level="read")
async def get_audit_summary(
    hours: int = 24,
    recent_limit: int = 20,
    all_time: bool = False,
) -> dict[str, Any]:
    """Summarize the immutable local audit stream and return its most recent events."""
    store = get_telemetry_store()
    summary = await store.audit_summary(
        hours=None if all_time else hours,
        recent_limit=recent_limit,
    )
    return {"ok": True, "audit": summary}
