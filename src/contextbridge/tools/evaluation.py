"""Read-only MCP access to persisted evaluation results."""
from __future__ import annotations

from typing import Any

from contextbridge.telemetry.instrumentation import get_telemetry_store, observed_tool


@observed_tool(risk_level="read")
async def get_evaluation_summary(run_id: str | None = None) -> dict[str, Any]:
    """Return the latest or specified local tool-selection evaluation summary. Read-only."""
    item = await get_telemetry_store().get_evaluation_run(run_id)
    if item is None:
        return {
            "ok": True,
            "available": False,
            "message": "No evaluation run has been recorded yet. Run contextbridge-eval --baseline locally.",
        }
    return {
        "ok": True,
        "available": True,
        "run_id": item["run_id"],
        "mode": item["mode"],
        "benchmark_name": item["benchmark_name"],
        "created_at": item["created_at"],
        "report": item["report"],
    }
