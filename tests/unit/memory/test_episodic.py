from pathlib import Path

import pytest

from atlas.contracts.types import Episode, EpisodeType
from atlas.memory.store import DatabaseStore
from atlas.memory.episodic import EpisodicMemoryStore


@pytest.fixture
async def episodic_store(tmp_path: Path):
    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()
    store = EpisodicMemoryStore(db)
    yield store
    await db.close()


async def test_record_and_retrieve(episodic_store: EpisodicMemoryStore):
    episode = Episode(
        episode_type=EpisodeType.TASK_EXECUTION,
        trigger="user goal",
        plan="read the file",
        outcome="file read successfully",
        tags=["filesystem"],
    )
    episode_id = await episodic_store.record(episode)
    assert episode_id == episode.episode_id

    result = await episodic_store.get_by_id(episode_id)
    assert result is not None
    assert result.trigger == "user goal"
    assert result.outcome == "file read successfully"


async def test_search_fts(episodic_store: EpisodicMemoryStore):
    await episodic_store.record(Episode(
        trigger="deploy the application",
        outcome="deployment succeeded",
    ))
    await episodic_store.record(Episode(
        trigger="fix the login bug",
        outcome="bug fixed",
    ))
    results = await episodic_store.search("deploy", limit=10)
    assert len(results) == 1
    assert "deploy" in results[0].trigger


async def test_query_recent(episodic_store: EpisodicMemoryStore):
    for i in range(5):
        await episodic_store.record(Episode(trigger=f"task-{i}", outcome=f"done-{i}"))
    results = await episodic_store.query_recent(limit=3)
    assert len(results) == 3


async def test_get_by_id_missing(episodic_store: EpisodicMemoryStore):
    result = await episodic_store.get_by_id("nonexistent")
    assert result is None
