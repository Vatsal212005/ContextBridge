from __future__ import annotations

import sqlite3

import pytest

from contextbridge.telemetry.store import TelemetryStore


@pytest.mark.asyncio
async def test_exact_pending_action_is_deduplicated(tmp_path) -> None:
    store = TelemetryStore(tmp_path / "contextbridge.db")
    first = await store.create_pending_action(
        tool_name="create_issue",
        risk_level="write",
        arguments={"owner": "o", "repo": "r", "title": "x", "body": None},
        ttl_minutes=30,
    )
    second = await store.create_pending_action(
        tool_name="create_issue",
        risk_level="write",
        arguments={"owner": "o", "repo": "r", "title": "x", "body": None},
        ttl_minutes=30,
    )
    assert first["action_id"] == second["action_id"]
    assert second["deduplicated"] is True
    assert second["signature_valid"] is True


@pytest.mark.asyncio
async def test_human_approval_generates_verifiable_approval_proof(tmp_path) -> None:
    store = TelemetryStore(tmp_path / "contextbridge.db")
    action = await store.create_pending_action(
        tool_name="close_issue",
        risk_level="destructive",
        arguments={"owner": "o", "repo": "r", "issue_number": 3},
        ttl_minutes=30,
    )
    approved = await store.decide_pending_action(
        action_id=action["action_id"],
        approve=True,
        actor="human:local_cli",
        reason="reviewed",
    )
    assert approved["status"] == "approved"
    assert approved["signature_valid"] is True
    assert approved["approval_valid"] is True


@pytest.mark.asyncio
async def test_tampered_arguments_cannot_be_approved(tmp_path) -> None:
    store = TelemetryStore(tmp_path / "contextbridge.db")
    action = await store.create_pending_action(
        tool_name="create_issue",
        risk_level="write",
        arguments={"owner": "o", "repo": "r", "title": "safe", "body": None},
        ttl_minutes=30,
    )
    with sqlite3.connect(store.database_path) as db:
        db.execute(
            "UPDATE pending_actions SET arguments_json = ? WHERE action_id = ?",
            ('{"body":null,"owner":"o","repo":"r","title":"tampered"}', action["action_id"]),
        )
        db.commit()

    result = await store.decide_pending_action(
        action_id=action["action_id"], approve=True, actor="human:test"
    )
    assert result["ok"] is False
    assert result["error"] == "action_signature_invalid"


@pytest.mark.asyncio
async def test_forged_approved_status_cannot_be_claimed(tmp_path) -> None:
    store = TelemetryStore(tmp_path / "contextbridge.db")
    action = await store.create_pending_action(
        tool_name="create_issue",
        risk_level="write",
        arguments={"owner": "o", "repo": "r", "title": "x", "body": None},
        ttl_minutes=30,
    )
    # A plain status flip is not human approval because it lacks the keyed approval proof.
    with sqlite3.connect(store.database_path) as db:
        db.execute(
            "UPDATE pending_actions SET status = 'approved', decided_at = datetime('now'), decided_by = 'fake' WHERE action_id = ?",
            (action["action_id"],),
        )
        db.commit()

    result = await store.claim_approved_action(action["action_id"])
    assert result["ok"] is False
    assert result["error"] == "approval_signature_invalid"


@pytest.mark.asyncio
async def test_approved_action_can_be_claimed_only_once(tmp_path) -> None:
    store = TelemetryStore(tmp_path / "contextbridge.db")
    action = await store.create_pending_action(
        tool_name="create_issue",
        risk_level="write",
        arguments={"owner": "o", "repo": "r", "title": "x", "body": None},
        ttl_minutes=30,
    )
    await store.decide_pending_action(
        action_id=action["action_id"], approve=True, actor="human:test"
    )
    first = await store.claim_approved_action(action["action_id"])
    second = await store.claim_approved_action(action["action_id"])
    assert first["ok"] is True
    assert first["status"] == "executing"
    assert second["ok"] is False
    assert second["status"] == "executing"


@pytest.mark.asyncio
async def test_existing_milestone5_database_is_migrated_in_place(tmp_path) -> None:
    db_path = tmp_path / "contextbridge.db"
    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE pending_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_id TEXT NOT NULL UNIQUE,
                tool_name TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                requested_at TEXT NOT NULL,
                expires_at TEXT,
                decided_at TEXT,
                decision_reason TEXT
            );
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        db.commit()

    store = TelemetryStore(db_path)
    await store.initialize()
    status = await store.database_status()
    assert status["schema_version"] == 4
    with sqlite3.connect(db_path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(pending_actions)")}
    assert "action_signature" in columns
    assert "approval_signature" in columns
    assert "request_fingerprint" in columns
