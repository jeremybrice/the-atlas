"""Audit Logger — append-only record of every significant ATLAS action."""

from __future__ import annotations

import json

import aiosqlite

from atlas.contracts.types import AuditEntry


class AuditLogger:
    """Append-only SQLite audit log."""

    def __init__(
        self, db_path: str | None = None, db: aiosqlite.Connection | None = None
    ):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = db
        self._owns_connection = db is None

    async def initialize(self) -> None:
        if self._db is None:
            self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                entry_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                correlation_id TEXT,
                actor TEXT NOT NULL,
                action_type TEXT NOT NULL,
                action_details TEXT NOT NULL,
                policy_decision TEXT,
                outcome TEXT NOT NULL,
                mission_id TEXT,
                task_id TEXT
            )
        """)
        await self._db.commit()

    async def close(self) -> None:
        if self._db and self._owns_connection:
            await self._db.close()

    async def log(self, entry: AuditEntry) -> None:
        if not self._db:
            return
        await self._db.execute(
            """INSERT INTO audit_log
               (entry_id, timestamp, correlation_id, actor, action_type,
                action_details, policy_decision, outcome, mission_id, task_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.entry_id,
                entry.timestamp.isoformat(),
                entry.correlation_id,
                entry.actor,
                entry.action_type,
                json.dumps(entry.action_details),
                entry.policy_decision.value if entry.policy_decision else None,
                entry.outcome,
                entry.mission_id,
                entry.task_id,
            ),
        )
        await self._db.commit()

    async def query(self, limit: int = 50) -> list[dict]:
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
