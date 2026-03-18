"""Procedural Memory — stores and retrieves learned workflow procedures."""

import json
from datetime import datetime, timezone

from atlas.contracts.types import Procedure
from atlas.memory.store import DatabaseStore


class ProceduralMemoryStore:
    def __init__(self, db: DatabaseStore):
        self._db = db

    async def initialize(self) -> None:
        await self._db.db.execute("""
            CREATE TABLE IF NOT EXISTS procedures (
                procedure_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                trigger_pattern TEXT,
                steps TEXT,
                success_rate REAL DEFAULT 0.0,
                use_count INTEGER DEFAULT 0,
                last_used TEXT,
                created_from TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self._db.db.commit()

    async def store(self, proc: Procedure) -> str:
        await self._db.db.execute(
            "INSERT INTO procedures (procedure_id, name, description, trigger_pattern, steps, success_rate, use_count, last_used, created_from) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                proc.procedure_id,
                proc.name,
                proc.description,
                proc.trigger_pattern,
                json.dumps(proc.steps),
                proc.success_rate,
                proc.use_count,
                proc.last_used,
                proc.created_from,
            ),
        )
        await self._db.db.commit()
        return proc.procedure_id

    async def get(self, procedure_id: str) -> Procedure | None:
        cursor = await self._db.db.execute(
            "SELECT * FROM procedures WHERE procedure_id = ?", (procedure_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_procedure(row)

    async def search_by_trigger(self, pattern: str) -> list[Procedure]:
        cursor = await self._db.db.execute(
            "SELECT * FROM procedures WHERE trigger_pattern = ? ORDER BY success_rate DESC",
            (pattern,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_procedure(r) for r in rows]

    async def record_outcome(self, procedure_id: str, success: bool) -> None:
        proc = await self.get(procedure_id)
        if not proc:
            return
        new_count = proc.use_count + 1
        total_successes = round(proc.success_rate * proc.use_count) + (
            1 if success else 0
        )
        new_rate = total_successes / new_count
        now = datetime.now(timezone.utc).isoformat()
        await self._db.db.execute(
            "UPDATE procedures SET success_rate = ?, use_count = ?, last_used = ? WHERE procedure_id = ?",
            (new_rate, new_count, now, procedure_id),
        )
        await self._db.db.commit()

    async def list_all(self) -> list[Procedure]:
        cursor = await self._db.db.execute(
            "SELECT * FROM procedures ORDER BY use_count DESC"
        )
        rows = await cursor.fetchall()
        return [self._row_to_procedure(r) for r in rows]

    def _row_to_procedure(self, row) -> Procedure:
        return Procedure(
            procedure_id=row[0],
            name=row[1],
            description=row[2] or "",
            trigger_pattern=row[3] or "",
            steps=json.loads(row[4]) if row[4] else [],
            success_rate=row[5] or 0.0,
            use_count=row[6] or 0,
            last_used=row[7] or "",
            created_from=row[8] or "",
        )
