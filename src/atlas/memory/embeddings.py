"""Embedding Provider — wraps Voyage AI for text embeddings."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import voyageai

if TYPE_CHECKING:
    from atlas.contracts.types import Episode

logger = logging.getLogger(__name__)


class EmbeddingProvider:
    """Wraps Voyage AI API for embedding text into vectors."""

    def __init__(self, api_key: str, model: str = "voyage-3-lite"):
        self._model = model
        self._client = voyageai.AsyncClient(api_key=api_key)

    async def embed(self, text: str) -> np.ndarray | None:
        """Embed a single text for storage (document input type). Returns None on error."""
        try:
            result = await self._client.embed([text], model=self._model, input_type="document")
            return np.array(result.embeddings[0], dtype=np.float32)
        except Exception as e:
            logger.warning("Embedding failed: %s", e)
            return None

    async def embed_query(self, text: str) -> np.ndarray | None:
        """Embed a query for search (query input type). Returns None on error."""
        try:
            result = await self._client.embed([text], model=self._model, input_type="query")
            return np.array(result.embeddings[0], dtype=np.float32)
        except Exception as e:
            logger.warning("Query embedding failed: %s", e)
            return None

    async def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        """Embed multiple texts for storage. Returns empty list on error."""
        try:
            result = await self._client.embed(texts, model=self._model, input_type="document")
            return [np.array(e, dtype=np.float32) for e in result.embeddings]
        except Exception as e:
            logger.warning("Batch embedding failed: %s", e)
            return []

    @staticmethod
    def compose_episode_text(episode: Episode) -> str:
        """Compose the text to embed for an episode."""
        parts = []
        if episode.trigger:
            parts.append(episode.trigger)
        if episode.plan:
            parts.append(episode.plan)
        if episode.outcome:
            parts.append(episode.outcome)
        if episode.lessons:
            parts.append(", ".join(episode.lessons))
        return " ".join(parts)
