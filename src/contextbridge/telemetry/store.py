"""SQLite persistence and observability for ContextBridge."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from contextbridge.telemetry.redaction import redact

SCHEMA_VERSION = 4

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    tool_name TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    error_type TEXT,
    error_message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_executions_started_at ON tool_executions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_executions_tool_name ON tool_executions(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_executions_status ON tool_executions(status);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    request_id TEXT,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    actor TEXT NOT NULL,
    tool_name TEXT,
    message TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_type ON audit_events(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_events_severity ON audit_events(severity);
CREATE TRIGGER IF NOT EXISTS audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;
CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

CREATE TABLE IF NOT EXISTS pending_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id TEXT NOT NULL UNIQUE,
    tool_name TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    requested_at TEXT NOT NULL,
    expires_at TEXT,
    decided_at TEXT,
    decision_reason TEXT,
    requested_by TEXT NOT NULL DEFAULT 'mcp_client',
    decided_by TEXT,
    request_fingerprint TEXT,
    action_signature TEXT,
    approval_signature TEXT,
    execution_started_at TEXT,
    executed_at TEXT,
    execution_result_json TEXT,
    execution_error_type TEXT,
    execution_error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_pending_actions_status ON pending_actions(status, requested_at DESC);

CREATE TABLE IF NOT EXISTS system_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_system_events_created_at ON system_events(created_at DESC);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL,
    benchmark_name TEXT NOT NULL,
    case_count INTEGER NOT NULL,
    predictions_received INTEGER NOT NULL,
    tool_selection_accuracy REAL NOT NULL,
    parameter_accuracy REAL,
    risk_accuracy REAL,
    mutation_classification_accuracy REAL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evaluation_runs_created_at ON evaluation_runs(created_at DESC);

CREATE TABLE IF NOT EXISTS evaluation_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    expected_tool TEXT NOT NULL,
    actual_tool TEXT,
    tool_correct INTEGER NOT NULL,
    parameter_score REAL,
    expected_risk TEXT NOT NULL,
    actual_risk TEXT,
    risk_correct INTEGER,
    confirmation_required INTEGER NOT NULL,
    mutation_classification_correct INTEGER,
    details_json TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES evaluation_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_evaluation_results_run_id ON evaluation_results(run_id);
CREATE INDEX IF NOT EXISTS idx_evaluation_results_case_id ON evaluation_results(case_id);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated ON chat_sessions(updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'complete',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, id ASC);

CREATE TABLE IF NOT EXISTS chat_tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    result_json TEXT,
    status TEXT NOT NULL,
    duration_ms REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chat_tool_calls_session ON chat_tool_calls(session_id, id ASC);
"""

Status = Literal["success", "error", "blocked", "confirmation_required"]
ActionStatus = Literal["pending", "approved", "rejected", "expired", "executing", "simulated", "executed", "failed"]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _json_dumps(value: Any) -> str:
    return json.dumps(redact(value), ensure_ascii=False, sort_keys=True, default=str)


def _loads(value: str) -> Any:
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    fraction = rank - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


class TelemetryStore:
    """SQLite telemetry store with async wrappers around short blocking operations."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False
        self._init_lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            await asyncio.to_thread(self._initialize_sync)
            self._initialized = True

    def _initialize_sync(self) -> None:
        with self._connect() as db:
            db.executescript(SCHEMA)
            self._migrate_pending_actions(db)
            db.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            db.commit()

    @staticmethod
    def _migrate_pending_actions(db: sqlite3.Connection) -> None:
        """Idempotently upgrade the Milestone 4/5 pending_actions table in place."""
        existing = {row["name"] for row in db.execute("PRAGMA table_info(pending_actions)").fetchall()}
        additions = {
            "requested_by": "TEXT NOT NULL DEFAULT 'mcp_client'",
            "decided_by": "TEXT",
            "request_fingerprint": "TEXT",
            "action_signature": "TEXT",
            "approval_signature": "TEXT",
            "execution_started_at": "TEXT",
            "executed_at": "TEXT",
            "execution_result_json": "TEXT",
            "execution_error_type": "TEXT",
            "execution_error_message": "TEXT",
        }
        for name, sql_type in additions.items():
            if name not in existing:
                db.execute(f"ALTER TABLE pending_actions ADD COLUMN {name} {sql_type}")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_actions_fingerprint "
            "ON pending_actions(request_fingerprint, status, expires_at)"
        )

    async def record_tool_execution(
        self,
        *,
        request_id: str,
        tool_name: str,
        risk_level: str,
        arguments: dict[str, Any],
        status: Status,
        duration_ms: float,
        started_at: datetime,
        finished_at: datetime,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        await self.initialize()
        await asyncio.to_thread(
            self._record_tool_execution_sync,
            request_id,
            tool_name,
            risk_level,
            arguments,
            status,
            duration_ms,
            started_at,
            finished_at,
            error_type,
            error_message,
        )

    def _record_tool_execution_sync(
        self,
        request_id: str,
        tool_name: str,
        risk_level: str,
        arguments: dict[str, Any],
        status: Status,
        duration_ms: float,
        started_at: datetime,
        finished_at: datetime,
        error_type: str | None,
        error_message: str | None,
    ) -> None:
        severity = "error" if status == "error" else "warning" if status in {
            "blocked",
            "confirmation_required",
        } else "info"
        event_id = f"evt_{uuid.uuid4().hex}"
        metadata = {
            "risk_level": risk_level,
            "status": status,
            "duration_ms": round(duration_ms, 3),
        }
        if error_type:
            metadata["error_type"] = error_type
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                INSERT INTO tool_executions (
                    request_id, tool_name, risk_level, arguments_json, status,
                    duration_ms, error_type, error_message, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    tool_name,
                    risk_level,
                    _json_dumps(arguments),
                    status,
                    duration_ms,
                    error_type,
                    error_message,
                    started_at.isoformat(),
                    finished_at.isoformat(),
                ),
            )
            db.execute(
                """
                INSERT INTO audit_events (
                    event_id, request_id, event_type, severity, actor, tool_name,
                    message, metadata_json, created_at
                ) VALUES (?, ?, 'tool_execution', ?, 'mcp_client', ?, ?, ?, ?)
                """,
                (
                    event_id,
                    request_id,
                    severity,
                    tool_name,
                    f"Tool {tool_name} completed with status {status}.",
                    _json_dumps(metadata),
                    finished_at.isoformat(),
                ),
            )
            db.commit()

    async def record_system_event(
        self,
        *,
        kind: str,
        status: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        await self.initialize()
        event_id = f"sys_{uuid.uuid4().hex}"
        await asyncio.to_thread(
            self._record_system_event_sync,
            event_id,
            kind,
            status,
            message,
            metadata or {},
        )
        return event_id

    def _record_system_event_sync(
        self,
        event_id: str,
        kind: str,
        status: str,
        message: str,
        metadata: dict[str, Any],
    ) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO system_events(event_id, kind, status, message, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, kind, status, message, _json_dumps(metadata), _utc_now().isoformat()),
            )
            db.commit()

    async def recent_tool_calls(
        self,
        *,
        limit: int = 25,
        tool_name: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        await self.initialize()
        limit = max(1, min(int(limit), 200))
        return await asyncio.to_thread(self._recent_tool_calls_sync, limit, tool_name, status)

    def _recent_tool_calls_sync(
        self,
        limit: int,
        tool_name: str | None,
        status: str | None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if tool_name:
            clauses.append("tool_name = ?")
            params.append(tool_name)
        if status:
            clauses.append("status = ?")
            params.append(status)
        query = "SELECT * FROM tool_executions"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["arguments"] = _loads(item.pop("arguments_json")) or {}
            item["duration_ms"] = round(float(item["duration_ms"]), 3)
            result.append(item)
        return result

    async def metrics(self, *, hours: int | None = 24) -> dict[str, Any]:
        await self.initialize()
        if hours is not None:
            hours = max(1, min(int(hours), 24 * 365))
        return await asyncio.to_thread(self._metrics_sync, hours)

    def _metrics_sync(self, hours: int | None) -> dict[str, Any]:
        where = ""
        params: list[Any] = []
        window_start: str | None = None
        if hours is not None:
            start_dt = _utc_now() - timedelta(hours=hours)
            window_start = start_dt.isoformat()
            where = " WHERE started_at >= ?"
            params.append(window_start)

        with self._connect() as db:
            rows = db.execute(
                f"SELECT tool_name, status, duration_ms, error_type FROM tool_executions{where}",
                params,
            ).fetchall()

        total = len(rows)
        successes = sum(1 for row in rows if row["status"] == "success")
        failures = sum(1 for row in rows if row["status"] == "error")
        blocked = sum(1 for row in rows if row["status"] == "blocked")
        confirmation_required = sum(
            1 for row in rows if row["status"] == "confirmation_required"
        )
        durations = [float(row["duration_ms"]) for row in rows]

        by_tool_map: dict[str, dict[str, Any]] = {}
        errors_by_type: dict[str, int] = {}
        for row in rows:
            name = row["tool_name"]
            bucket = by_tool_map.setdefault(
                name,
                {"tool_name": name, "calls": 0, "successes": 0, "errors": 0, "duration_total": 0.0},
            )
            bucket["calls"] += 1
            bucket["duration_total"] += float(row["duration_ms"])
            if row["status"] == "success":
                bucket["successes"] += 1
            elif row["status"] == "error":
                bucket["errors"] += 1
                error_type = row["error_type"] or "unknown"
                errors_by_type[error_type] = errors_by_type.get(error_type, 0) + 1

        by_tool: list[dict[str, Any]] = []
        for bucket in by_tool_map.values():
            calls = bucket.pop("calls")
            duration_total = bucket.pop("duration_total")
            successes_for_tool = bucket["successes"]
            bucket["calls"] = calls
            bucket["success_rate_pct"] = round(successes_for_tool / calls * 100, 2) if calls else 0.0
            bucket["avg_latency_ms"] = round(duration_total / calls, 3) if calls else 0.0
            by_tool.append(bucket)
        by_tool.sort(key=lambda item: (-item["calls"], item["tool_name"]))

        return {
            "window": {
                "hours": hours,
                "started_at": window_start,
                "ended_at": _utc_now().isoformat(),
            },
            "totals": {
                "calls": total,
                "successes": successes,
                "failures": failures,
                "blocked": blocked,
                "confirmation_required": confirmation_required,
                "success_rate_pct": round(successes / total * 100, 2) if total else 0.0,
                "avg_latency_ms": round(sum(durations) / total, 3) if total else 0.0,
                "p95_latency_ms": round(_percentile(durations, 0.95), 3) if total else 0.0,
            },
            "by_tool": by_tool,
            "errors_by_type": dict(sorted(errors_by_type.items(), key=lambda item: (-item[1], item[0]))),
        }

    async def audit_summary(self, *, hours: int | None = 24, recent_limit: int = 20) -> dict[str, Any]:
        await self.initialize()
        if hours is not None:
            hours = max(1, min(int(hours), 24 * 365))
        recent_limit = max(1, min(int(recent_limit), 100))
        return await asyncio.to_thread(self._audit_summary_sync, hours, recent_limit)

    def _audit_summary_sync(self, hours: int | None, recent_limit: int) -> dict[str, Any]:
        where = ""
        params: list[Any] = []
        window_start: str | None = None
        if hours is not None:
            start_dt = _utc_now() - timedelta(hours=hours)
            window_start = start_dt.isoformat()
            where = " WHERE created_at >= ?"
            params.append(window_start)

        with self._connect() as db:
            audit_rows = db.execute(
                f"SELECT * FROM audit_events{where} ORDER BY id DESC",
                params,
            ).fetchall()
            pending_count = int(
                db.execute("SELECT COUNT(*) AS c FROM pending_actions WHERE status = 'pending'").fetchone()["c"]
            )
            system_count = int(db.execute("SELECT COUNT(*) AS c FROM system_events").fetchone()["c"])

        severity_counts: dict[str, int] = {}
        event_type_counts: dict[str, int] = {}
        for row in audit_rows:
            severity_counts[row["severity"]] = severity_counts.get(row["severity"], 0) + 1
            event_type_counts[row["event_type"]] = event_type_counts.get(row["event_type"], 0) + 1

        recent: list[dict[str, Any]] = []
        for row in audit_rows[:recent_limit]:
            item = dict(row)
            item["metadata"] = _loads(item.pop("metadata_json")) or {}
            recent.append(item)

        return {
            "window": {"hours": hours, "started_at": window_start, "ended_at": _utc_now().isoformat()},
            "total_events": len(audit_rows),
            "severity_counts": severity_counts,
            "event_type_counts": event_type_counts,
            "pending_actions": pending_count,
            "system_events_all_time": system_count,
            "recent_events": recent,
        }

    def _action_key_path(self) -> Path:
        return self.database_path.with_name(self.database_path.name + ".action-key")

    def _load_or_create_action_key_sync(self) -> bytes:
        path = self._action_key_path()
        try:
            data = path.read_bytes()
            if len(data) < 32:
                raise RuntimeError(f"Action signing key at {path} is invalid.")
            return data
        except FileNotFoundError:
            key = secrets.token_bytes(32)
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                data = path.read_bytes()
                if len(data) < 32:
                    raise RuntimeError(f"Action signing key at {path} is invalid.")
                return data
            with os.fdopen(fd, "wb") as handle:
                handle.write(key)
            return key

    @staticmethod
    def _action_arguments_json(arguments: dict[str, Any]) -> str:
        # Pending-action payloads contain only the narrowly validated mutation
        # arguments, never credentials. Keep the exact payload so an approved
        # action can be executed without mutation or truncation.
        return json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def _request_fingerprint(cls, *, tool_name: str, risk_level: str, arguments: dict[str, Any]) -> str:
        material = f"{tool_name}\n{risk_level}\n{cls._action_arguments_json(arguments)}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def _action_signature_sync(
        self,
        *,
        action_id: str,
        tool_name: str,
        risk_level: str,
        arguments_json: str,
        requested_at: str,
        expires_at: str,
    ) -> str:
        key = self._load_or_create_action_key_sync()
        material = "\n".join(
            [action_id, tool_name, risk_level, arguments_json, requested_at, expires_at]
        ).encode("utf-8")
        return hmac.new(key, material, hashlib.sha256).hexdigest()

    def _verify_action_signature_sync(self, row: sqlite3.Row | dict[str, Any]) -> bool:
        item = dict(row)
        signature = item.get("action_signature")
        if not signature:
            return False
        expected = self._action_signature_sync(
            action_id=str(item["action_id"]),
            tool_name=str(item["tool_name"]),
            risk_level=str(item["risk_level"]),
            arguments_json=str(item["arguments_json"]),
            requested_at=str(item["requested_at"]),
            expires_at=str(item["expires_at"]),
        )
        return hmac.compare_digest(str(signature), expected)

    def _approval_signature_sync(
        self, *, action_signature: str, decided_at: str, decided_by: str
    ) -> str:
        key = self._load_or_create_action_key_sync()
        material = f"{action_signature}\n{decided_at}\n{decided_by}\napproved".encode("utf-8")
        return hmac.new(key, material, hashlib.sha256).hexdigest()

    def _verify_approval_signature_sync(self, row: sqlite3.Row | dict[str, Any]) -> bool:
        item = dict(row)
        approval = item.get("approval_signature")
        action_signature = item.get("action_signature")
        decided_at = item.get("decided_at")
        decided_by = item.get("decided_by")
        if not all([approval, action_signature, decided_at, decided_by]):
            return False
        expected = self._approval_signature_sync(
            action_signature=str(action_signature),
            decided_at=str(decided_at),
            decided_by=str(decided_by),
        )
        return hmac.compare_digest(str(approval), expected)

    @staticmethod
    def _action_from_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["arguments"] = _loads(item.pop("arguments_json")) or {}
        result_json = item.pop("execution_result_json", None)
        item["execution_result"] = _loads(result_json) if result_json else None
        return item

    def _append_action_audit_sync(
        self,
        db: sqlite3.Connection,
        *,
        action_id: str,
        event_type: str,
        severity: str,
        actor: str,
        tool_name: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        db.execute(
            """
            INSERT INTO audit_events (
                event_id, request_id, event_type, severity, actor, tool_name,
                message, metadata_json, created_at
            ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"evt_{uuid.uuid4().hex}",
                event_type,
                severity,
                actor,
                tool_name,
                message,
                _json_dumps({"action_id": action_id, **(metadata or {})}),
                _utc_now().isoformat(),
            ),
        )

    async def create_pending_action(
        self,
        *,
        tool_name: str,
        risk_level: str,
        arguments: dict[str, Any],
        ttl_minutes: int,
        requested_by: str = "mcp_client",
    ) -> dict[str, Any]:
        await self.initialize()
        ttl_minutes = max(1, min(int(ttl_minutes), 1440))
        return await asyncio.to_thread(
            self._create_pending_action_sync,
            tool_name,
            risk_level,
            arguments,
            ttl_minutes,
            requested_by,
        )

    def _create_pending_action_sync(
        self,
        tool_name: str,
        risk_level: str,
        arguments: dict[str, Any],
        ttl_minutes: int,
        requested_by: str,
    ) -> dict[str, Any]:
        now = _utc_now()
        expires = now + timedelta(minutes=ttl_minutes)
        args_json = self._action_arguments_json(arguments)
        fingerprint = self._request_fingerprint(
            tool_name=tool_name, risk_level=risk_level, arguments=arguments
        )
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire_stale_actions_in_connection(db, now=now)
            existing = db.execute(
                """
                SELECT * FROM pending_actions
                WHERE request_fingerprint = ?
                  AND status IN ('pending', 'approved')
                  AND expires_at > ?
                ORDER BY id DESC LIMIT 1
                """,
                (fingerprint, now.isoformat()),
            ).fetchone()
            if existing is not None and self._verify_action_signature_sync(existing):
                db.commit()
                item = self._action_from_row(existing)
                item["deduplicated"] = True
                item["signature_valid"] = True
                item["approval_valid"] = self._verify_approval_signature_sync(existing)
                return item

            action_id = f"act_{secrets.token_urlsafe(18)}"
            requested_at = now.isoformat()
            expires_at = expires.isoformat()
            signature = self._action_signature_sync(
                action_id=action_id,
                tool_name=tool_name,
                risk_level=risk_level,
                arguments_json=args_json,
                requested_at=requested_at,
                expires_at=expires_at,
            )
            db.execute(
                """
                INSERT INTO pending_actions (
                    action_id, tool_name, risk_level, arguments_json, status,
                    requested_at, expires_at, requested_by, request_fingerprint,
                    action_signature
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    tool_name,
                    risk_level,
                    args_json,
                    requested_at,
                    expires_at,
                    requested_by,
                    fingerprint,
                    signature,
                ),
            )
            self._append_action_audit_sync(
                db,
                action_id=action_id,
                event_type="action_requested",
                severity="warning",
                actor=requested_by,
                tool_name=tool_name,
                message=f"Human confirmation requested for {tool_name}.",
                metadata={"risk_level": risk_level, "expires_at": expires_at},
            )
            row = db.execute(
                "SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            db.commit()
        item = self._action_from_row(row)
        item["deduplicated"] = False
        item["signature_valid"] = True
        item["approval_valid"] = False
        return item

    def _expire_stale_actions_in_connection(
        self, db: sqlite3.Connection, *, now: datetime | None = None
    ) -> int:
        now = now or _utc_now()
        rows = db.execute(
            """
            SELECT action_id, tool_name FROM pending_actions
            WHERE status IN ('pending', 'approved') AND expires_at <= ?
            """,
            (now.isoformat(),),
        ).fetchall()
        if not rows:
            return 0
        db.execute(
            """
            UPDATE pending_actions
            SET status = 'expired', decided_at = COALESCE(decided_at, ?),
                decision_reason = COALESCE(decision_reason, 'confirmation_ttl_expired')
            WHERE status IN ('pending', 'approved') AND expires_at <= ?
            """,
            (now.isoformat(), now.isoformat()),
        )
        for row in rows:
            self._append_action_audit_sync(
                db,
                action_id=row["action_id"],
                event_type="action_expired",
                severity="warning",
                actor="system",
                tool_name=row["tool_name"],
                message="Pending action expired before execution.",
            )
        return len(rows)

    async def list_pending_actions(
        self, *, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        await self.initialize()
        limit = max(1, min(int(limit), 200))
        allowed = {"pending", "approved", "rejected", "expired", "executing", "simulated", "executed", "failed"}
        if status is not None and status not in allowed:
            raise ValueError(f"status must be one of: {', '.join(sorted(allowed))}")
        return await asyncio.to_thread(self._list_pending_actions_sync, status, limit)

    def _list_pending_actions_sync(self, status: str | None, limit: int) -> list[dict[str, Any]]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire_stale_actions_in_connection(db)
            query = "SELECT * FROM pending_actions"
            params: list[Any] = []
            if status:
                query += " WHERE status = ?"
                params.append(status)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = db.execute(query, params).fetchall()
            db.commit()
        result = []
        for row in rows:
            item = self._action_from_row(row)
            item["signature_valid"] = self._verify_action_signature_sync(row)
            item["approval_valid"] = self._verify_approval_signature_sync(row)
            result.append(item)
        return result

    async def get_pending_action(self, action_id: str) -> dict[str, Any] | None:
        await self.initialize()
        return await asyncio.to_thread(self._get_pending_action_sync, action_id)

    def _get_pending_action_sync(self, action_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire_stale_actions_in_connection(db)
            row = db.execute(
                "SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            db.commit()
        if row is None:
            return None
        item = self._action_from_row(row)
        item["signature_valid"] = self._verify_action_signature_sync(row)
        item["approval_valid"] = self._verify_approval_signature_sync(row)
        return item

    async def decide_pending_action(
        self,
        *,
        action_id: str,
        approve: bool,
        actor: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        await self.initialize()
        return await asyncio.to_thread(
            self._decide_pending_action_sync, action_id, approve, actor, reason
        )

    def _decide_pending_action_sync(
        self, action_id: str, approve: bool, actor: str, reason: str | None
    ) -> dict[str, Any]:
        now = _utc_now()
        new_status = "approved" if approve else "rejected"
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire_stale_actions_in_connection(db, now=now)
            row = db.execute(
                "SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            if row is None:
                db.rollback()
                return {"ok": False, "status": "not_found", "action_id": action_id}
            if not self._verify_action_signature_sync(row):
                self._append_action_audit_sync(
                    db,
                    action_id=action_id,
                    event_type="action_tamper_detected",
                    severity="error",
                    actor=actor,
                    tool_name=row["tool_name"],
                    message="Action signature verification failed; decision refused.",
                )
                db.commit()
                return {
                    "ok": False,
                    "status": "blocked",
                    "action_id": action_id,
                    "error": "action_signature_invalid",
                }
            current = row["status"]
            if current not in {"pending", "approved"}:
                db.rollback()
                return {
                    "ok": False,
                    "status": current,
                    "action_id": action_id,
                    "error": "action_not_decidable",
                }
            if approve and current == "approved":
                if not self._verify_approval_signature_sync(row):
                    db.rollback()
                    return {
                        "ok": False,
                        "status": "blocked",
                        "action_id": action_id,
                        "error": "approval_signature_invalid",
                    }
                db.commit()
                item = self._action_from_row(row)
                item["ok"] = True
                item["signature_valid"] = True
                item["approval_valid"] = True
                return item
            decided_at = now.isoformat()
            approval_signature = (
                self._approval_signature_sync(
                    action_signature=str(row["action_signature"]),
                    decided_at=decided_at,
                    decided_by=actor,
                )
                if approve
                else None
            )
            db.execute(
                """
                UPDATE pending_actions
                SET status = ?, decided_at = ?, decided_by = ?, decision_reason = ?,
                    approval_signature = ?
                WHERE action_id = ? AND status IN ('pending', 'approved')
                """,
                (new_status, decided_at, actor, reason, approval_signature, action_id),
            )
            self._append_action_audit_sync(
                db,
                action_id=action_id,
                event_type="action_approved" if approve else "action_rejected",
                severity="warning" if approve else "info",
                actor=actor,
                tool_name=row["tool_name"],
                message=(
                    "Human approved exact pending action."
                    if approve
                    else "Human rejected pending action."
                ),
                metadata={"reason": reason},
            )
            updated = db.execute(
                "SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            db.commit()
        item = self._action_from_row(updated)
        item["ok"] = True
        item["signature_valid"] = True
        item["approval_valid"] = approve
        return item

    async def claim_approved_action(self, action_id: str) -> dict[str, Any]:
        await self.initialize()
        return await asyncio.to_thread(self._claim_approved_action_sync, action_id)

    def _claim_approved_action_sync(self, action_id: str) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire_stale_actions_in_connection(db, now=now)
            row = db.execute(
                "SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            if row is None:
                db.rollback()
                return {"ok": False, "status": "not_found", "action_id": action_id}
            if not self._verify_action_signature_sync(row):
                self._append_action_audit_sync(
                    db,
                    action_id=action_id,
                    event_type="action_tamper_detected",
                    severity="error",
                    actor="mcp_client",
                    tool_name=row["tool_name"],
                    message="Action signature verification failed; execution refused.",
                )
                db.commit()
                return {
                    "ok": False,
                    "status": "blocked",
                    "action_id": action_id,
                    "error": "action_signature_invalid",
                }
            if row["status"] != "approved":
                db.rollback()
                return {
                    "ok": False,
                    "status": row["status"],
                    "action_id": action_id,
                    "error": "action_not_approved",
                }
            if not self._verify_approval_signature_sync(row):
                self._append_action_audit_sync(
                    db,
                    action_id=action_id,
                    event_type="approval_tamper_detected",
                    severity="error",
                    actor="mcp_client",
                    tool_name=row["tool_name"],
                    message="Human approval proof failed verification; execution refused.",
                )
                db.commit()
                return {
                    "ok": False,
                    "status": "blocked",
                    "action_id": action_id,
                    "error": "approval_signature_invalid",
                }
            changed = db.execute(
                """
                UPDATE pending_actions
                SET status = 'executing', execution_started_at = ?
                WHERE action_id = ? AND status = 'approved'
                """,
                (now.isoformat(), action_id),
            ).rowcount
            if changed != 1:
                db.rollback()
                return {
                    "ok": False,
                    "status": "race_lost",
                    "action_id": action_id,
                    "error": "action_claim_failed",
                }
            self._append_action_audit_sync(
                db,
                action_id=action_id,
                event_type="action_execution_claimed",
                severity="warning",
                actor="mcp_client",
                tool_name=row["tool_name"],
                message="Approved action was atomically claimed for one-time execution.",
            )
            updated = db.execute(
                "SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            db.commit()
        item = self._action_from_row(updated)
        item["ok"] = True
        item["signature_valid"] = True
        item["approval_valid"] = True
        return item

    async def finalize_action(
        self,
        *,
        action_id: str,
        status: Literal["simulated", "executed", "failed"],
        result: dict[str, Any] | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        actor: str = "mcp_client",
    ) -> dict[str, Any]:
        await self.initialize()
        return await asyncio.to_thread(
            self._finalize_action_sync,
            action_id,
            status,
            result,
            error_type,
            error_message,
            actor,
        )

    def _finalize_action_sync(
        self,
        action_id: str,
        status: str,
        result: dict[str, Any] | None,
        error_type: str | None,
        error_message: str | None,
        actor: str,
    ) -> dict[str, Any]:
        if status not in {"simulated", "executed", "failed"}:
            raise ValueError("invalid final action status")
        now = _utc_now().isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            if row is None:
                db.rollback()
                return {"ok": False, "status": "not_found", "action_id": action_id}
            if row["status"] != "executing":
                db.rollback()
                return {
                    "ok": False,
                    "status": row["status"],
                    "action_id": action_id,
                    "error": "action_not_executing",
                }
            db.execute(
                """
                UPDATE pending_actions
                SET status = ?, executed_at = ?, execution_result_json = ?,
                    execution_error_type = ?, execution_error_message = ?
                WHERE action_id = ? AND status = 'executing'
                """,
                (
                    status,
                    now,
                    json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
                    if result is not None
                    else None,
                    error_type,
                    error_message[:1000] if error_message else None,
                    action_id,
                ),
            )
            self._append_action_audit_sync(
                db,
                action_id=action_id,
                event_type=f"action_{status}",
                severity="error" if status == "failed" else "info",
                actor=actor,
                tool_name=row["tool_name"],
                message=f"Pending action finished with status {status}.",
                metadata={"error_type": error_type},
            )
            updated = db.execute(
                "SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            db.commit()
        item = self._action_from_row(updated)
        item["ok"] = status in {"simulated", "executed"}
        item["signature_valid"] = self._verify_action_signature_sync(updated)
        item["approval_valid"] = self._verify_approval_signature_sync(updated)
        return item


    async def record_evaluation_run(
        self,
        *,
        mode: str,
        benchmark_name: str,
        report: dict[str, Any],
        results: list[dict[str, Any]],
    ) -> str:
        """Persist one evaluation run and its case-level results."""
        await self.initialize()
        run_id = f"eval_{uuid.uuid4().hex}"
        await asyncio.to_thread(
            self._record_evaluation_run_sync, run_id, mode, benchmark_name, report, results
        )
        return run_id

    def _record_evaluation_run_sync(
        self,
        run_id: str,
        mode: str,
        benchmark_name: str,
        report: dict[str, Any],
        results: list[dict[str, Any]],
    ) -> None:
        created_at = _utc_now().isoformat()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO evaluation_runs(
                    run_id, mode, benchmark_name, case_count, predictions_received,
                    tool_selection_accuracy, parameter_accuracy, risk_accuracy,
                    mutation_classification_accuracy, report_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    mode,
                    benchmark_name,
                    int(report.get("cases", 0)),
                    int(report.get("predictions_received", 0)),
                    float(report.get("tool_selection_accuracy_pct", 0.0)),
                    report.get("parameter_accuracy_pct"),
                    report.get("risk_accuracy_pct"),
                    report.get("mutation_classification_accuracy_pct"),
                    _json_dumps(report),
                    created_at,
                ),
            )
            for row in results:
                db.execute(
                    """
                    INSERT INTO evaluation_results(
                        run_id, case_id, prompt, expected_tool, actual_tool, tool_correct,
                        parameter_score, expected_risk, actual_risk, risk_correct,
                        confirmation_required, mutation_classification_correct, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        str(row.get("id")),
                        str(row.get("prompt", "")),
                        str(row.get("expected_tool", "")),
                        row.get("actual_tool"),
                        1 if row.get("tool_correct") else 0,
                        row.get("parameter_score"),
                        str(row.get("expected_risk", "read")),
                        row.get("actual_risk"),
                        None if row.get("risk_correct") is None else (1 if row.get("risk_correct") else 0),
                        1 if row.get("confirmation_required") else 0,
                        None if row.get("mutation_classification_correct") is None else (1 if row.get("mutation_classification_correct") else 0),
                        _json_dumps(row),
                    ),
                )
            db.execute(
                """
                INSERT INTO system_events(event_id, kind, status, message, metadata_json, created_at)
                VALUES (?, 'evaluation_run', 'ok', ?, ?, ?)
                """,
                (
                    f"sys_{uuid.uuid4().hex}",
                    f"Evaluation {run_id} completed.",
                    _json_dumps({
                        "run_id": run_id,
                        "mode": mode,
                        "tool_selection_accuracy_pct": report.get("tool_selection_accuracy_pct"),
                    }),
                    created_at,
                ),
            )
            db.commit()

    async def list_evaluation_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        await self.initialize()
        limit = max(1, min(int(limit), 100))
        return await asyncio.to_thread(self._list_evaluation_runs_sync, limit)

    def _list_evaluation_runs_sync(self, limit: int) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM evaluation_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["report"] = _loads(item.pop("report_json")) or {}
            result.append(item)
        return result

    async def get_evaluation_run(self, run_id: str | None = None) -> dict[str, Any] | None:
        await self.initialize()
        return await asyncio.to_thread(self._get_evaluation_run_sync, run_id)

    def _get_evaluation_run_sync(self, run_id: str | None) -> dict[str, Any] | None:
        with self._connect() as db:
            if run_id:
                row = db.execute("SELECT * FROM evaluation_runs WHERE run_id = ?", (run_id,)).fetchone()
            else:
                row = db.execute("SELECT * FROM evaluation_runs ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                return None
            result_rows = db.execute(
                "SELECT * FROM evaluation_results WHERE run_id = ? ORDER BY id ASC",
                (row["run_id"],),
            ).fetchall()
        item = dict(row)
        item["report"] = _loads(item.pop("report_json")) or {}
        case_results: list[dict[str, Any]] = []
        for rr in result_rows:
            detail = _loads(rr["details_json"]) or {}
            case_results.append(detail)
        item["results"] = case_results
        return item

    async def create_chat_session(self, *, provider: str, model: str, title: str = "New conversation") -> dict[str, Any]:
        await self.initialize()
        return await asyncio.to_thread(self._create_chat_session_sync, provider, model, title)

    def _create_chat_session_sync(self, provider: str, model: str, title: str) -> dict[str, Any]:
        session_id = f"chat_{uuid.uuid4().hex}"
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute("INSERT INTO chat_sessions(session_id,title,provider,model,created_at,updated_at) VALUES(?,?,?,?,?,?)", (session_id, title[:160], provider, model, now, now))
            db.commit()
        return {"session_id": session_id, "title": title[:160], "provider": provider, "model": model, "created_at": now, "updated_at": now}

    async def get_chat_session(self, session_id: str) -> dict[str, Any] | None:
        await self.initialize()
        return await asyncio.to_thread(self._get_chat_session_sync, session_id)

    def _get_chat_session_sync(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone()
        return dict(row) if row else None

    async def list_chat_sessions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        await self.initialize()
        return await asyncio.to_thread(self._list_chat_sessions_sync, max(1, min(limit, 200)))

    def _list_chat_sessions_sync(self, limit: int) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM chat_sessions ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
            result=[]
            for row in rows:
                item=dict(row)
                item["message_count"] = int(db.execute("SELECT COUNT(*) c FROM chat_messages WHERE session_id=?", (row["session_id"],)).fetchone()["c"])
                result.append(item)
            return result

    async def delete_chat_session(self, session_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._delete_chat_session_sync, session_id)

    def _delete_chat_session_sync(self, session_id: str) -> bool:
        with self._connect() as db:
            cur=db.execute("DELETE FROM chat_sessions WHERE session_id=?", (session_id,))
            db.commit()
            return cur.rowcount > 0

    async def add_chat_message(self, *, session_id: str, role: str, content: str, status: str = "complete", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        await self.initialize()
        return await asyncio.to_thread(self._add_chat_message_sync, session_id, role, content, status, metadata or {})

    def _add_chat_message_sync(self, session_id: str, role: str, content: str, status: str, metadata: dict[str, Any]) -> dict[str, Any]:
        message_id=f"msg_{uuid.uuid4().hex}"
        now=datetime.now(UTC).isoformat()
        with self._connect() as db:
            if db.execute("SELECT 1 FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone() is None:
                raise KeyError(session_id)
            db.execute("INSERT INTO chat_messages(message_id,session_id,role,content,status,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)", (message_id,session_id,role,content,status,_json_dumps(metadata),now))
            db.execute("UPDATE chat_sessions SET updated_at=? WHERE session_id=?", (now,session_id))
            if role == "user":
                row=db.execute("SELECT COUNT(*) c FROM chat_messages WHERE session_id=? AND role='user'", (session_id,)).fetchone()
                if row["c"] == 1:
                    title=" ".join(content.strip().split())[:80] or "New conversation"
                    db.execute("UPDATE chat_sessions SET title=? WHERE session_id=?", (title,session_id))
            db.commit()
        return {"message_id":message_id,"session_id":session_id,"role":role,"content":content,"status":status,"metadata":redact(metadata),"created_at":now}

    async def list_chat_messages(self, *, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        await self.initialize()
        return await asyncio.to_thread(self._list_chat_messages_sync, session_id, max(1,min(limit,500)))

    def _list_chat_messages_sync(self, session_id: str, limit: int) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows=db.execute("SELECT * FROM (SELECT * FROM chat_messages WHERE session_id=? ORDER BY id DESC LIMIT ?) ORDER BY id ASC", (session_id,limit)).fetchall()
        out=[]
        for row in rows:
            item=dict(row); item["metadata"]=_loads(item.pop("metadata_json")) or {}; out.append(item)
        return out

    async def record_chat_tool_call(self, *, session_id: str, turn_id: str, call_id: str, tool_name: str, risk_level: str, arguments: dict[str, Any], result: dict[str, Any] | None, status: str, duration_ms: float) -> None:
        await self.initialize()
        await asyncio.to_thread(self._record_chat_tool_call_sync, session_id,turn_id,call_id,tool_name,risk_level,arguments,result,status,duration_ms)

    def _record_chat_tool_call_sync(self, session_id: str, turn_id: str, call_id: str, tool_name: str, risk_level: str, arguments: dict[str, Any], result: dict[str, Any] | None, status: str, duration_ms: float) -> None:
        now=datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO chat_tool_calls(call_id,session_id,turn_id,tool_name,risk_level,arguments_json,result_json,status,duration_ms,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (call_id,session_id,turn_id,tool_name,risk_level,_json_dumps(arguments),_json_dumps(result) if result is not None else None,status,float(duration_ms),now))
            db.commit()

    async def list_chat_tool_calls(self, *, session_id: str, limit: int = 300) -> list[dict[str, Any]]:
        await self.initialize()
        return await asyncio.to_thread(self._list_chat_tool_calls_sync, session_id,max(1,min(limit,500)))

    def _list_chat_tool_calls_sync(self, session_id: str, limit: int) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows=db.execute("SELECT * FROM chat_tool_calls WHERE session_id=? ORDER BY id ASC LIMIT ?", (session_id,limit)).fetchall()
        out=[]
        for row in rows:
            item=dict(row); item["arguments"]=_loads(item.pop("arguments_json")) or {}; raw=item.pop("result_json"); item["result"]=_loads(raw) if raw else None; out.append(item)
        return out

    async def database_status(self) -> dict[str, Any]:
        await self.initialize()
        return await asyncio.to_thread(self._database_status_sync)

    def _database_status_sync(self) -> dict[str, Any]:
        with self._connect() as db:
            schema_version = db.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()["value"]
            tables = [
                row["name"]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]
            counts = {
                table: int(db.execute(f'SELECT COUNT(*) AS c FROM "{table}"').fetchone()["c"])
                for table in tables
                if table != "schema_meta"
            }
        return {
            "database_path": str(self.database_path),
            "schema_version": int(schema_version),
            "tables": tables,
            "row_counts": counts,
            "size_bytes": self.database_path.stat().st_size if self.database_path.exists() else 0,
        }
