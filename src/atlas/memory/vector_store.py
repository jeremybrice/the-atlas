"""Vector Store — SQLite-backed embedding storage with cosine similarity search."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np

from atlas.memory.store import DatabaseStore

logger = logging.getLogger(__name__)


class VectorStore:
    """Stores and searches embeddings using SQLite BLOBs and numpy cosine similarity."""

    def __init__(self, db: DatabaseStore, model: str = "voyage-3-lite"):
        self._db = db
        self._model = model

    async def store(self, episode_id: str, embedding: np.ndarray) -> None:
        """Store an embedding for an episode."""
        await self._db.db.execute(
            """INSERT OR REPLACE INTO episode_embeddings
               (episode_id, embedding, model, dimensions, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                episode_id,
                embedding.tobytes(),
                self._model,
                len(embedding),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await self._db.db.commit()

    async def store_batch(self, episode_ids: list[str], embeddings: list[np.ndarray]) -> None:
        """Store embeddings for multiple episodes."""
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (eid, emb.tobytes(), self._model, len(emb), now)
            for eid, emb in zip(episode_ids, embeddings)
        ]
        await self._db.db.executemany(
            """INSERT OR REPLACE INTO episode_embeddings
               (episode_id, embedding, model, dimensions, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            rows,
        )
        await self._db.db.commit()

    async def get(self, episode_id: str) -> np.ndarray | None:
        """Retrieve an embedding by episode ID."""
        cursor = await self._db.db.execute(
            "SELECT embedding, dimensions FROM episode_embeddings WHERE episode_id = ?",
            (episode_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return np.frombuffer(row[0], dtype=np.float32).copy()

    async def search(self, query_embedding: np.ndarray, limit: int = 50) -> list[tuple[str, float]]:
        """Search for similar episodes by cosine similarity.

        Returns list of (episode_id, similarity_score) sorted by score descending.
        """
        cursor = await self._db.db.execute(
            "SELECT episode_id, embedding FROM episode_embeddings"
        )
        rows = await cursor.fetchall()

        if not rows:
            return []

        # Compute cosine similarity for all stored embeddings
        query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-10)
        scored = []
        for episode_id, blob in rows:
            stored = np.frombuffer(blob, dtype=np.float32)
            stored_norm = stored / (np.linalg.norm(stored) + 1e-10)
            similarity = float(np.dot(query_norm, stored_norm))
            # Clamp to [0, 1] range
            similarity = max(0.0, min(1.0, similarity))
            scored.append((episode_id, similarity))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def has_embedding(self, episode_id: str) -> bool:
        """Check if an episode has a stored embedding."""
        cursor = await self._db.db.execute(
            "SELECT 1 FROM episode_embeddings WHERE episode_id = ?",
            (episode_id,),
        )
        return await cursor.fetchone() is not None

    async def count(self) -> int:
        """Return the number of stored embeddings."""
        cursor = await self._db.db.execute("SELECT COUNT(*) FROM episode_embeddings")
        row = await cursor.fetchone()
        return row[0]
