from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from contextbridge.telemetry.redaction import redact
from contextbridge.telemetry.store import TelemetryStore


@pytest.mark.asyncio
async def test_schema_initializes_all_milestone4_tables(tmp_path) -> None:
    db_path = tmp_path / "contextbridge.db"
    store = TelemetryStore(db_path)
    await store.initialize()

    with sqlite3.connect(db_path) as db:
        names = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }

    assert {
        "schema_meta",
        "tool_executions",
        "audit_events",
        "pending_actions",
        "system_events",
        "evaluation_runs",
        "evaluation_results",
    }.issubset(names)


@pytest.mark.asyncio
async def test_record_execution_creates_tool_and_audit_rows(tmp_path) -> None:
    store = TelemetryStore(tmp_path / "contextbridge.db")
    started = datetime.now(UTC) - timedelta(milliseconds=5)
    finished = datetime.now(UTC)

    await store.record_tool_execution(
        request_id="req_test",
        tool_name="search_issues",
        risk_level="read",
        arguments={"query": "bug", "token": "never-store-this"},
        status="success",
        duration_ms=5.25,
        started_at=started,
        finished_at=finished,
    )

    recent = await store.recent_tool_calls(limit=10)
    audit = await store.audit_summary(hours=None, recent_limit=10)

    assert len(recent) == 1
    assert recent[0]["tool_name"] == "search_issues"
    assert recent[0]["arguments"]["token"] == "[REDACTED]"
    assert audit["total_events"] == 1
    assert audit["recent_events"][0]["request_id"] == "req_test"


@pytest.mark.asyncio
async def test_metrics_report_success_failure_and_p95(tmp_path) -> None:
    store = TelemetryStore(tmp_path / "contextbridge.db")
    now = datetime.now(UTC)
    for idx, (status, duration, error_type) in enumerate(
        [
            ("success", 10.0, None),
            ("success", 20.0, None),
            ("error", 100.0, "github_rate_limited"),
        ]
    ):
        await store.record_tool_execution(
            request_id=f"req_{idx}",
            tool_name="list_repositories" if idx < 2 else "search_code",
            risk_level="read",
            arguments={},
            status=status,
            duration_ms=duration,
            started_at=now,
            finished_at=now,
            error_type=error_type,
            error_message="rate limited" if error_type else None,
        )

    metrics = await store.metrics(hours=None)
    assert metrics["totals"]["calls"] == 3
    assert metrics["totals"]["successes"] == 2
    assert metrics["totals"]["failures"] == 1
    assert metrics["totals"]["success_rate_pct"] == pytest.approx(66.67, abs=0.01)
    assert metrics["totals"]["p95_latency_ms"] > 90
    assert metrics["errors_by_type"]["github_rate_limited"] == 1


@pytest.mark.asyncio
async def test_recent_tool_call_filters(tmp_path) -> None:
    store = TelemetryStore(tmp_path / "contextbridge.db")
    now = datetime.now(UTC)
    for idx, (tool, status) in enumerate([("health", "success"), ("search_code", "error")]):
        await store.record_tool_execution(
            request_id=f"req_filter_{idx}",
            tool_name=tool,
            risk_level="read",
            arguments={},
            status=status,
            duration_ms=1.0,
            started_at=now,
            finished_at=now,
            error_type="example" if status == "error" else None,
        )

    rows = await store.recent_tool_calls(limit=10, status="error")
    assert len(rows) == 1
    assert rows[0]["tool_name"] == "search_code"


@pytest.mark.asyncio
async def test_audit_events_are_database_enforced_append_only(tmp_path) -> None:
    store = TelemetryStore(tmp_path / "contextbridge.db")
    now = datetime.now(UTC)
    await store.record_tool_execution(
        request_id="req_immutable",
        tool_name="health",
        risk_level="read",
        arguments={},
        status="success",
        duration_ms=1.0,
        started_at=now,
        finished_at=now,
    )

    with sqlite3.connect(store.database_path) as db:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("UPDATE audit_events SET message = 'changed' WHERE request_id = ?", ("req_immutable",))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM audit_events WHERE request_id = ?", ("req_immutable",))


def test_redaction_is_recursive_and_bounds_large_strings() -> None:
    value = redact(
        {
            "authorization": "Bearer secret",
            "nested": {"api_key": "secret", "query": "x" * 2100},
        }
    )
    assert value["authorization"] == "[REDACTED]"
    assert value["nested"]["api_key"] == "[REDACTED]"
    assert "truncated" in value["nested"]["query"]
