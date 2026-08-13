from __future__ import annotations

import pytest

from contextbridge.telemetry.instrumentation import observed_tool, set_telemetry_store_for_tests
from contextbridge.telemetry.store import TelemetryStore


@pytest.fixture
def isolated_store(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.db")
    set_telemetry_store_for_tests(store)
    try:
        yield store
    finally:
        set_telemetry_store_for_tests(None)


@pytest.mark.asyncio
async def test_observed_tool_records_success(isolated_store: TelemetryStore) -> None:
    @observed_tool(tool_name="demo", risk_level="read")
    async def demo(query: str = "hello") -> dict[str, object]:
        return {"ok": True, "query": query}

    result = await demo("world")
    rows = await isolated_store.recent_tool_calls(limit=5)

    assert result["ok"] is True
    assert rows[0]["tool_name"] == "demo"
    assert rows[0]["status"] == "success"
    assert rows[0]["arguments"]["query"] == "world"


@pytest.mark.asyncio
async def test_observed_tool_records_structured_failure(isolated_store: TelemetryStore) -> None:
    @observed_tool(tool_name="demo_failure", risk_level="read")
    async def demo_failure() -> dict[str, object]:
        return {
            "ok": False,
            "error": {"type": "not_found", "message": "missing"},
        }

    await demo_failure()
    rows = await isolated_store.recent_tool_calls(limit=5)

    assert rows[0]["status"] == "error"
    assert rows[0]["error_type"] == "not_found"


@pytest.mark.asyncio
async def test_observed_tool_records_exception_then_reraises(isolated_store: TelemetryStore) -> None:
    @observed_tool(tool_name="explode", risk_level="read")
    async def explode() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await explode()

    rows = await isolated_store.recent_tool_calls(limit=5)
    assert rows[0]["status"] == "error"
    assert rows[0]["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_observed_tool_records_policy_block(isolated_store: TelemetryStore) -> None:
    @observed_tool(tool_name="blocked_demo", risk_level="write")
    async def blocked_demo() -> dict[str, object]:
        return {
            "ok": False,
            "status": "blocked",
            "blocked": True,
            "error": {"type": "write_policy_blocked", "message": "dry run"},
        }

    await blocked_demo()
    rows = await isolated_store.recent_tool_calls(limit=5)

    assert rows[0]["status"] == "blocked"
    assert rows[0]["risk_level"] == "write"
    assert rows[0]["error_type"] == "write_policy_blocked"
