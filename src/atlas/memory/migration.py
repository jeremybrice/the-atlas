"""Vector Migration — batch-embeds existing episodes that lack embeddings."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from atlas.memory.embeddings import EmbeddingProvider
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.store import DatabaseStore
from atlas.memory.vector_store import VectorStore

logger = logging.getLogger(__name__)

MIGRATION_KEY = "vector_migration_complete"


class VectorMigration:
    """One-time migration: embeds all existing episodes without embeddings."""

    def __init__(
        self,
        db: DatabaseStore,
        episodic: EpisodicMemoryStore,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
    ):
        self._db = db
        self._episodic = episodic
        self._vector_store = vector_store
        self._provider = embedding_provider

    async def is_complete(self) -> bool:
        """Check if migration has already run."""
        cursor = await self._db.db.execute(
            "SELECT value FROM metadata WHERE key = ?", (MIGRATION_KEY,)
        )
        return await cursor.fetchone() is not None

    async def run(self) -> int:
        """Run migration. Returns count of newly embedded episodes."""
        if await self.is_complete():
            logger.info("Vector migration already complete, skipping")
            return 0

        # Get all episodes
        episodes = await self._episodic.query_recent(limit=100_000)
        if not episodes:
            await self._mark_complete()
            return 0

        # Filter out already-embedded episodes
        unembedded = []
        for ep in episodes:
            if not await self._vector_store.has_embedding(ep.episode_id):
                unembedded.append(ep)

        if not unembedded:
            await self._mark_complete()
            return 0

        # Batch embed in chunks to respect API limits
        batch_size = 128
        total_embedded = 0

        for i in range(0, len(unembedded), batch_size):
            chunk = unembedded[i : i + batch_size]
            texts = [self._provider.compose_episode_text(ep) for ep in chunk]
            embeddings = await self._provider.embed_batch(texts)

            if not embeddings:
                logger.warning(
                    "Embedding API failed on chunk %d — migration will retry on next startup",
                    i // batch_size,
                )
                return total_embedded

            ids = [ep.episode_id for ep in chunk[: len(embeddings)]]
            await self._vector_store.store_batch(ids, embeddings)
            total_embedded += len(embeddings)

            if len(embeddings) < len(chunk):
                logger.warning(
                    "Partial chunk: %d/%d — migration will retry on next startup",
                    len(embeddings),
                    len(chunk),
                )
                return total_embedded

        logger.info("Migrated %d episodes to vector store", total_embedded)
        await self._mark_complete()
        return total_embedded

    async def _mark_complete(self) -> None:
        """Mark migration as complete in metadata table."""
        await self._db.db.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (MIGRATION_KEY, datetime.now(timezone.utc).isoformat()),
        )
        await self._db.db.commit()
