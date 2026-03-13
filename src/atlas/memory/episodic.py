"""Episodic Memory — chronological record of agent actions and observations."""

from __future__ import annotations

import json

from atlas.contracts.types import Episode, EpisodeType
from atlas.memory.store import DatabaseStore


class EpisodicMemoryStore:
    """SQLite-backed episodic memory with FTS5 full-text search."""

    def __init__(self, db: DatabaseStore):
        self._db = db

    async def record(self, episode: Episode) -> str:
        await self._db.db.execute(
            """INSERT INTO episodes
               (episode_id, timestamp, episode_type, trigger_text, plan,
                actions, outcome, lessons, mission_id, task_id, tags, correlation_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                episode.episode_id,
                episode.timestamp.isoformat(),
                episode.episode_type.value,
                episode.trigger,
                episode.plan,
                json.dumps(episode.actions),
                episode.outcome,
                json.dumps(episode.lessons),
                episode.mission_id,
                episode.task_id,
                json.dumps(episode.tags),
                episode.correlation_id,
            ),
        )
        await self._db.db.commit()
        return episode.episode_id

    async def get_by_id(self, episode_id: str) -> Episode | None:
        cursor = await self._db.db.execute(
            "SELECT * FROM episodes WHERE episode_id = ?", (episode_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_episode(cursor.description, row)

    async def search(self, text_query: str, limit: int = 20) -> list[Episode]:
        cursor = await self._db.db.execute(
            """SELECT e.* FROM episodes e
               JOIN episodes_fts fts ON e.episode_id = fts.episode_id
               WHERE episodes_fts MATCH ?
               ORDER BY e.timestamp DESC LIMIT ?""",
            (text_query, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_episode(cursor.description, row) for row in rows]

    async def query_recent(self, limit: int = 50) -> list[Episode]:
        cursor = await self._db.db.execute(
            "SELECT * FROM episodes ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_episode(cursor.description, row) for row in rows]

    def _row_to_episode(self, description, row) -> Episode:
        cols = [desc[0] for desc in description]
        data = dict(zip(cols, row))
        return Episode(
            episode_id=data["episode_id"],
            episode_type=EpisodeType(data["episode_type"]),
            trigger=data.get("trigger_text", ""),
            plan=data.get("plan", ""),
            actions=json.loads(data.get("actions", "[]")),
            outcome=data.get("outcome", ""),
            lessons=json.loads(data.get("lessons", "[]")),
            mission_id=data.get("mission_id"),
            task_id=data.get("task_id"),
            tags=json.loads(data.get("tags", "[]")),
            correlation_id=data.get("correlation_id"),
        )
