"""Episodic Memory — chronological record of agent actions and observations."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from atlas.contracts.types import Episode, EpisodeType
from atlas.memory.store import DatabaseStore

if TYPE_CHECKING:
    from atlas.memory.embeddings import EmbeddingProvider
    from atlas.memory.vector_store import VectorStore

logger = logging.getLogger(__name__)


class EpisodicMemoryStore:
    """SQLite-backed episodic memory with FTS5 full-text search."""

    def __init__(
        self,
        db: DatabaseStore,
        embedding_provider: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
    ):
        self._db = db
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store

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

        # Embed and store vector if provider is available
        if self._embedding_provider and self._vector_store:
            try:
                text = self._embedding_provider.compose_episode_text(episode)
                embedding = await self._embedding_provider.embed(text)
                if embedding is not None:
                    await self._vector_store.store(episode.episode_id, embedding)
                else:
                    logger.warning("Failed to embed episode %s, will retry on migration", episode.episode_id)
            except Exception as e:
                logger.warning("Embedding failed for episode %s: %s", episode.episode_id, e)

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

    async def search_scored(self, text_query: str, limit: int = 20) -> list[tuple[str, float]]:
        """Search episodes and return (episode_id, relevance_score) tuples.

        Scores are normalized FTS5 rank values in [0, 1] range.
        Each token is individually quoted for FTS5 safety (prevents reserved
        words like AND/OR/NOT from being parsed as operators) while allowing
        per-token matching instead of exact phrase search.
        """
        if not text_query or not text_query.strip():
            return []
        # Quote each token individually for FTS5 safety without requiring phrase match
        tokens = text_query.split()
        safe_tokens = ['"' + t.replace('"', '""') + '"' for t in tokens if t.strip()]
        if not safe_tokens:
            return []
        safe_query = " ".join(safe_tokens)
        cursor = await self._db.db.execute(
            """SELECT e.episode_id, rank
               FROM episodes e
               JOIN episodes_fts fts ON e.episode_id = fts.episode_id
               WHERE episodes_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (safe_query, limit),
        )
        rows = await cursor.fetchall()
        if not rows:
            return []

        # FTS5 rank is negative (more negative = more relevant)
        # Normalize to [0, 1] where 1 = most relevant
        raw_scores = [(r[0], -r[1]) for r in rows]  # flip sign
        max_score = max(s for _, s in raw_scores) if raw_scores else 1.0
        if max_score == 0:
            max_score = 1.0
        return [(eid, score / max_score) for eid, score in raw_scores]

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
