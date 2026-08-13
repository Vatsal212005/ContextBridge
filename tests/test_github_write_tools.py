from __future__ import annotations

from pathlib import Path

import pytest

from contextbridge.config import Settings
from contextbridge.telemetry.instrumentation import set_telemetry_store_for_tests
from contextbridge.telemetry.store import TelemetryStore
import contextbridge.tools.github_write as write_tools


@pytest.fixture
async def safe_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = Settings(
        github_token="token-that-must-not-be-used",
        database_path=tmp_path / "telemetry.db",
        dry_run=True,
        github_writes_enabled=False,
        github_write_repositories=(),
        confirmation_ttl_minutes=30,
    )
    store = TelemetryStore(cfg.database_path)
    set_telemetry_store_for_tests(store)
    monkeypatch.setattr(write_tools, "settings", cfg)
    yield cfg, store
    set_telemetry_store_for_tests(None)


def _explode_client():
    raise AssertionError("GitHub client must not be constructed in Milestone 6A dry-run mode")


@pytest.mark.asyncio
async def test_create_issue_queues_confirmation_without_constructing_client(
    monkeypatch: pytest.MonkeyPatch, safe_runtime
) -> None:
    _, _store = safe_runtime
    monkeypatch.setattr(write_tools, "_client", _explode_client)
    result = await write_tools.create_issue("owner", "repo", "test issue", "test body")

    assert result["ok"] is False
    assert result["status"] == "confirmation_required"
    assert result["github_request_sent"] is False
    assert result["action"]["status"] == "pending"
    assert result["action"]["risk_level"] == "write"
    assert result["human_confirmation"]["mcp_approval_available"] is False


@pytest.mark.asyncio
async def test_close_issue_is_destructive_and_requires_confirmation(safe_runtime) -> None:
    result = await write_tools.close_issue("owner", "repo", 7)
    assert result["status"] == "confirmation_required"
    assert result["action"]["risk_level"] == "destructive"


@pytest.mark.asyncio
async def test_pending_action_cannot_execute_without_human_approval(
    monkeypatch: pytest.MonkeyPatch, safe_runtime
) -> None:
    monkeypatch.setattr(write_tools, "_client", _explode_client)
    requested = await write_tools.create_issue("owner", "repo", "x")
    action_id = requested["action"]["action_id"]

    result = await write_tools.execute_approved_action(action_id)
    assert result["status"] == "confirmation_required"
    assert result["confirmation_required"] is True


@pytest.mark.asyncio
async def test_approved_action_is_simulated_once_in_dry_run(
    monkeypatch: pytest.MonkeyPatch, safe_runtime
) -> None:
    _, store = safe_runtime
    monkeypatch.setattr(write_tools, "_client", _explode_client)
    requested = await write_tools.create_issue("owner", "repo", "x", "body")
    action_id = requested["action"]["action_id"]

    approved = await store.decide_pending_action(
        action_id=action_id,
        approve=True,
        actor="human:test",
        reason="test approval",
    )
    assert approved["status"] == "approved"

    result = await write_tools.execute_approved_action(action_id)
    assert result["ok"] is True
    assert result["status"] == "simulated"
    assert result["github_request_sent"] is False

    second = await write_tools.execute_approved_action(action_id)
    assert second["ok"] is False
    assert second["status"] == "blocked"
    assert second["action"]["status"] == "simulated"


@pytest.mark.asyncio
async def test_rejected_action_cannot_execute(monkeypatch: pytest.MonkeyPatch, safe_runtime) -> None:
    _, store = safe_runtime
    monkeypatch.setattr(write_tools, "_client", _explode_client)
    requested = await write_tools.create_issue("owner", "repo", "x")
    action_id = requested["action"]["action_id"]
    rejected = await store.decide_pending_action(
        action_id=action_id, approve=False, actor="human:test", reason="no"
    )
    assert rejected["status"] == "rejected"

    result = await write_tools.execute_approved_action(action_id)
    assert result["status"] == "blocked"
    assert result["action"]["status"] == "rejected"


@pytest.mark.asyncio
async def test_write_policy_reports_human_confirmation_not_exposed_to_mcp(safe_runtime) -> None:
    result = await write_tools.get_write_policy()
    prohibited = set(result["prohibited_capabilities_not_implemented"])
    assert "delete_repository" in prohibited
    assert "delete_file" in prohibited
    assert "merge_pull_request" in prohibited
    assert result["dry_run"] is True
    assert result["github_writes_enabled"] is False
    assert result["human_confirmation"]["required_for_every_mutation"] is True
    assert result["human_confirmation"]["approval_exposed_as_mcp_tool"] is False
