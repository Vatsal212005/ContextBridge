"""Tool execution instrumentation shared by every MCP tool."""

from __future__ import annotations

import inspect
import time
import uuid
from datetime import UTC, datetime
from functools import wraps
from typing import Any, Awaitable, Callable, ParamSpec, TypeVar, cast

from contextbridge.config import settings
from contextbridge.telemetry.store import TelemetryStore

P = ParamSpec("P")
R = TypeVar("R")

_store: TelemetryStore | None = None


def get_telemetry_store() -> TelemetryStore:
    global _store
    if _store is None:
        _store = TelemetryStore(settings.database_path)
    return _store


def set_telemetry_store_for_tests(store: TelemetryStore | None) -> None:
    """Override/reset the process-global telemetry store in tests."""
    global _store
    _store = store


def _bound_arguments(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
        bound.apply_defaults()
        return dict(bound.arguments)
    except (TypeError, ValueError):
        return {"args": list(args), "kwargs": kwargs}


def _error_type(exc: BaseException) -> str:
    kind = getattr(exc, "kind", None)
    if kind:
        return str(kind)
    return exc.__class__.__name__


def _structured_outcome(result: Any) -> tuple[str, str | None, str | None]:
    """Map a structured tool response to telemetry status/error metadata."""
    if not isinstance(result, dict):
        return "success", None, None

    explicit_status = str(result.get("status") or "").lower()
    if result.get("blocked") is True or explicit_status == "blocked":
        error = result.get("error")
        if isinstance(error, dict):
            return (
                "blocked",
                str(error.get("type") or "policy_blocked"),
                str(error.get("message") or "Tool execution was blocked by policy.")[:1_000],
            )
        return "blocked", "policy_blocked", "Tool execution was blocked by policy."

    if explicit_status == "confirmation_required":
        return "confirmation_required", "confirmation_required", "Human confirmation is required."

    failed = result.get("ok") is False or result.get("connected") is False
    if not failed:
        return "success", None, None
    error = result.get("error")
    if isinstance(error, dict):
        return (
            "error",
            str(error.get("type") or "reported_failure"),
            str(error.get("message") or "Tool reported failure.")[:1_000],
        )
    return "error", "reported_failure", "Tool reported failure."


def observed_tool(
    *,
    tool_name: str | None = None,
    risk_level: str = "read",
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorate a tool so each execution is recorded in SQLite and the audit log."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        resolved_name = tool_name or func.__name__

        if inspect.iscoroutinefunction(func):
            async_func = cast(Callable[P, Awaitable[Any]], func)

            @wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                store = get_telemetry_store()
                request_id = f"req_{uuid.uuid4().hex}"
                started_at = datetime.now(UTC)
                started_perf = time.perf_counter()
                arguments = _bound_arguments(func, args, kwargs)
                try:
                    result = await async_func(*args, **kwargs)
                except Exception as exc:
                    finished_at = datetime.now(UTC)
                    await store.record_tool_execution(
                        request_id=request_id,
                        tool_name=resolved_name,
                        risk_level=risk_level,
                        arguments=arguments,
                        status="error",
                        duration_ms=(time.perf_counter() - started_perf) * 1000,
                        started_at=started_at,
                        finished_at=finished_at,
                        error_type=_error_type(exc),
                        error_message=str(exc)[:1_000],
                    )
                    raise
                finished_at = datetime.now(UTC)
                outcome_status, reported_error_type, reported_error_message = _structured_outcome(result)
                await store.record_tool_execution(
                    request_id=request_id,
                    tool_name=resolved_name,
                    risk_level=risk_level,
                    arguments=arguments,
                    status=cast(Any, outcome_status),
                    duration_ms=(time.perf_counter() - started_perf) * 1000,
                    started_at=started_at,
                    finished_at=finished_at,
                    error_type=reported_error_type,
                    error_message=reported_error_message,
                )
                return result

            return cast(Callable[P, R], async_wrapper)

        @wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            # MCPServer can invoke sync tools from its async runtime. A synchronous
            # wrapper cannot safely await telemetry, so run the original function
            # unchanged here. ContextBridge registers system tools through explicit
            # async shims in server.py so all registered MCP calls are still observed.
            return func(*args, **kwargs)

        return cast(Callable[P, R], sync_wrapper)

    return decorator
