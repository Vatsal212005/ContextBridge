"""System-level MCP tools used to verify the server is healthy."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from contextbridge.config import settings
from contextbridge.telemetry.instrumentation import observed_tool


@observed_tool(risk_level="read")
async def server_info() -> dict[str, Any]:
    """Return identity and runtime information for this ContextBridge server."""
    return {
        "name": settings.name,
        "version": settings.version,
        "status": "healthy",
        "environment": settings.environment,
        "transport": settings.transport,
    }


@observed_tool(risk_level="read")
async def health() -> dict[str, Any]:
    """Return a lightweight health check for the ContextBridge process."""
    return {
        "status": "healthy",
        "service": settings.name,
        "version": settings.version,
        "checked_at": datetime.now(UTC).isoformat(),
    }
