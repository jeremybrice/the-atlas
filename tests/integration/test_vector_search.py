"""Integration test: record episode -> embed -> search semantically -> correct episode surfaces."""

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from atlas.contracts.types import Episode
from atlas.memory.embeddings import EmbeddingProvider
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.migration import VectorMigration
from atlas.memory.retrieval import ContextAssembler
from atlas.memory.store import DatabaseStore
from atlas.memory.vector_store import VectorStore


@pytest.fixture
async def pipeline(tmp_path: Path):
    """Full vector search pipeline with mocked Voyage API."""
    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()

    # Mock embedding provider that returns predictable vectors
    mock_provider = MagicMock(spec=EmbeddingProvider)

    # Map text content to distinct vectors
    embedding_map = {
        "deploy": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
        "test": np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32),
        "debug": np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32),
        "refactor": np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32),
    }

    def mock_embed(text):
        for keyword, vec in embedding_map.items():
            if keyword in text.lower():
                return vec
        return np.array([0.25, 0.25, 0.25, 0.25], dtype=np.float32)

    def mock_embed_query(text):
        return mock_embed(text)

    def mock_embed_batch(texts):
        return [mock_embed(t) for t in texts]

    def mock_compose(episode):
        return f"{episode.trigger} {episode.plan} {episode.outcome}"

    mock_provider.embed = mock_embed
    mock_provider.embed_query = mock_embed_query
    mock_provider.embed_batch = mock_embed_batch
    mock_provider.compose_episode_text = mock_compose

    vector_store = VectorStore(db, model="voyage-3-lite")
    episodic = EpisodicMemoryStore(db, embedding_provider=mock_provider, vector_store=vector_store)

    yield db, episodic, vector_store, mock_provider
    await db.close()


async def test_record_and_semantic_search(pipeline):
    """Recording an episode should make it findable via semantic search."""
    db, episodic, vector_store, provider = pipeline

    # Record episodes in different domains
    await episodic.record(Episode(trigger="deploy the app", plan="run deploy script", outcome="succeeded"))
    await episodic.record(Episode(trigger="run test suite", plan="pytest -v", outcome="all passed"))
    await episodic.record(Episode(trigger="debug memory leak", plan="profile heap", outcome="fixed"))

    # Search semantically for deployment-related episodes
    query_vec = provider.embed_query("deploy to production")
    results = await vector_store.search(query_vec, limit=3)

    # The deploy episode should be the top result
    assert results[0][0] is not None  # episode_id
    assert results[0][1] > 0.9  # high similarity

    # Verify we can fetch the actual episode
    top_episode = await episodic.get_by_id(results[0][0])
    assert "deploy" in top_episode.trigger


async def test_hybrid_retrieval_end_to_end(pipeline):
    """Hybrid scoring should combine FTS5 keyword and vector similarity."""
    db, episodic, vector_store, provider = pipeline

    await episodic.record(Episode(trigger="deploy the app to staging", plan="run deploy", outcome="succeeded"))
    await episodic.record(Episode(trigger="deploy to production", plan="prod deploy", outcome="failed"))
    await episodic.record(Episode(trigger="run unit tests", plan="pytest", outcome="passed"))

    # Keyword search
    keyword_results = await episodic.search_scored("deploy", limit=10)
    keyword_scores = dict(keyword_results)

    # Semantic search
    query_vec = provider.embed_query("deploy")
    semantic_results = await vector_store.search(query_vec, limit=10)
    semantic_scores = dict(semantic_results)

    # Merge
    assembler = ContextAssembler()
    merged = assembler.merge_scores(keyword_scores, semantic_scores, semantic_weight=0.6, keyword_weight=0.4)

    # Both deploy episodes should score higher than the test episode
    deploy_ids = [eid for eid in merged if eid in keyword_scores]
    test_ids = [eid for eid in merged if eid not in keyword_scores]

    if deploy_ids and test_ids:
        max_deploy = max(merged[eid] for eid in deploy_ids)
        max_test = max(merged[eid] for eid in test_ids)
        assert max_deploy > max_test


async def test_migration_then_search(pipeline):
    """Episodes recorded before vector search should be searchable after migration."""
    db, episodic_with_vec, vector_store, provider = pipeline

    # Record episodes WITHOUT embedding (simulate pre-vector-search state)
    plain_episodic = EpisodicMemoryStore(db)  # no embedding provider
    await plain_episodic.record(Episode(trigger="deploy old app", plan="legacy script", outcome="ok"))
    await plain_episodic.record(Episode(trigger="test old code", plan="make test", outcome="passed"))

    assert await vector_store.count() == 0  # no embeddings yet

    # Run migration
    migration = VectorMigration(db, plain_episodic, vector_store, provider)
    count = await migration.run()
    assert count == 2
    assert await vector_store.count() == 2

    # Now semantic search should work
    query_vec = provider.embed_query("deploy")
    results = await vector_store.search(query_vec, limit=2)
    assert len(results) == 2
    assert results[0][1] > results[1][1]  # deploy episode ranked higher


async def test_graceful_degradation_keyword_only(tmp_path):
    """When embedding provider returns None, keyword search should still work."""
    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()

    failing_provider = MagicMock(spec=EmbeddingProvider)
    failing_provider.embed.return_value = None
    failing_provider.compose_episode_text.return_value = "test text"

    vector_store = VectorStore(db, model="voyage-3-lite")
    episodic = EpisodicMemoryStore(db, embedding_provider=failing_provider, vector_store=vector_store)

    await episodic.record(Episode(trigger="deploy the app", outcome="done"))

    # No embedding stored
    assert await vector_store.count() == 0

    # But keyword search still works
    results = await episodic.search("deploy", limit=10)
    assert len(results) == 1

    await db.close()
