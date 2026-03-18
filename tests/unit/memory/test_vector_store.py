from pathlib import Path

import numpy as np
import pytest

from atlas.memory.store import DatabaseStore
from atlas.memory.vector_store import VectorStore


@pytest.fixture
async def vector_store(tmp_path: Path):
    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()
    store = VectorStore(db, model="voyage-3-lite")
    yield store
    await db.close()


async def test_store_and_retrieve(vector_store: VectorStore):
    embedding = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    await vector_store.store("ep-1", embedding)

    results = await vector_store.get("ep-1")
    assert results is not None
    np.testing.assert_array_almost_equal(results, embedding)


async def test_store_batch(vector_store: VectorStore):
    embeddings = [
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        np.array([0.0, 1.0, 0.0], dtype=np.float32),
    ]
    await vector_store.store_batch(["ep-1", "ep-2"], embeddings)

    r1 = await vector_store.get("ep-1")
    r2 = await vector_store.get("ep-2")
    assert r1 is not None
    assert r2 is not None


async def test_search_returns_sorted_by_similarity(vector_store: VectorStore):
    # Store three vectors
    await vector_store.store("ep-exact", np.array([1.0, 0.0, 0.0], dtype=np.float32))
    await vector_store.store("ep-similar", np.array([0.9, 0.1, 0.0], dtype=np.float32))
    await vector_store.store(
        "ep-different", np.array([0.0, 0.0, 1.0], dtype=np.float32)
    )

    query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    results = await vector_store.search(query, limit=3)

    assert len(results) == 3
    # Results are (episode_id, score) tuples sorted by score descending
    assert results[0][0] == "ep-exact"
    assert results[1][0] == "ep-similar"
    assert results[2][0] == "ep-different"
    # Scores should be between 0 and 1
    assert all(0.0 <= score <= 1.0 for _, score in results)


async def test_search_respects_limit(vector_store: VectorStore):
    for i in range(10):
        await vector_store.store(f"ep-{i}", np.random.rand(3).astype(np.float32))

    query = np.random.rand(3).astype(np.float32)
    results = await vector_store.search(query, limit=5)
    assert len(results) == 5


async def test_get_missing_returns_none(vector_store: VectorStore):
    result = await vector_store.get("nonexistent")
    assert result is None


async def test_has_embedding(vector_store: VectorStore):
    await vector_store.store("ep-1", np.array([1.0, 0.0], dtype=np.float32))
    assert await vector_store.has_embedding("ep-1") is True
    assert await vector_store.has_embedding("ep-missing") is False


async def test_count(vector_store: VectorStore):
    assert await vector_store.count() == 0
    await vector_store.store("ep-1", np.array([1.0], dtype=np.float32))
    await vector_store.store("ep-2", np.array([0.5], dtype=np.float32))
    assert await vector_store.count() == 2
