from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from atlas.contracts.types import Episode
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.migration import VectorMigration
from atlas.memory.store import DatabaseStore
from atlas.memory.vector_store import VectorStore


@pytest.fixture
async def migration_deps(tmp_path: Path):
    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()
    vector_store = VectorStore(db, model="voyage-3-lite")
    episodic = EpisodicMemoryStore(db)

    mock_provider = MagicMock()
    mock_provider.compose_episode_text.return_value = "test text"
    mock_provider.embed_batch = AsyncMock(return_value=[
        np.array([0.1, 0.2, 0.3], dtype=np.float32),
        np.array([0.4, 0.5, 0.6], dtype=np.float32),
    ])

    yield db, episodic, vector_store, mock_provider
    await db.close()


async def test_migration_embeds_existing_episodes(migration_deps):
    db, episodic, vector_store, mock_provider = migration_deps

    # Record episodes without embeddings
    await episodic.record(Episode(trigger="goal one", outcome="done"))
    await episodic.record(Episode(trigger="goal two", outcome="done"))

    migration = VectorMigration(db, episodic, vector_store, mock_provider)
    count = await migration.run()
    assert count == 2
    assert await vector_store.count() == 2


async def test_migration_skips_already_embedded(migration_deps):
    db, episodic, vector_store, mock_provider = migration_deps

    ep = Episode(trigger="goal one", outcome="done")
    await episodic.record(ep)
    # Manually embed this one
    await vector_store.store(ep.episode_id, np.array([0.1, 0.2, 0.3], dtype=np.float32))

    await episodic.record(Episode(trigger="goal two", outcome="done"))

    mock_provider.embed_batch = AsyncMock(return_value=[
        np.array([0.4, 0.5, 0.6], dtype=np.float32),
    ])

    migration = VectorMigration(db, episodic, vector_store, mock_provider)
    count = await migration.run()
    assert count == 1  # only the un-embedded one


async def test_migration_marks_complete(migration_deps):
    db, episodic, vector_store, mock_provider = migration_deps

    await episodic.record(Episode(trigger="goal one", outcome="done"))

    mock_provider.embed_batch = AsyncMock(return_value=[
        np.array([0.1, 0.2, 0.3], dtype=np.float32),
    ])

    migration = VectorMigration(db, episodic, vector_store, mock_provider)
    await migration.run()

    assert await migration.is_complete() is True


async def test_migration_noop_if_already_complete(migration_deps):
    db, episodic, vector_store, mock_provider = migration_deps

    await episodic.record(Episode(trigger="goal one", outcome="done"))

    mock_provider.embed_batch.return_value = [
        np.array([0.1, 0.2, 0.3], dtype=np.float32),
    ]

    migration = VectorMigration(db, episodic, vector_store, mock_provider)
    await migration.run()
    count = await migration.run()  # second run
    assert count == 0


async def test_migration_does_not_mark_complete_on_api_failure(migration_deps):
    """If embed_batch returns [] (API failure), migration should NOT mark complete."""
    db, episodic, vector_store, mock_provider = migration_deps

    await episodic.record(Episode(trigger="goal one", outcome="done"))
    mock_provider.embed_batch = AsyncMock(return_value=[])  # API failure

    migration = VectorMigration(db, episodic, vector_store, mock_provider)
    count = await migration.run()
    assert count == 0
    assert await migration.is_complete() is False
