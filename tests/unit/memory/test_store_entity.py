import pytest
from atlas.memory.store import DatabaseStore


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


async def test_entity_mappings_table_exists(db):
    cursor = await db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='entity_mappings'"
    )
    row = await cursor.fetchone()
    assert row is not None


async def test_entity_mappings_columns(db):
    cursor = await db.db.execute("PRAGMA table_info(entity_mappings)")
    columns = {row[1] for row in await cursor.fetchall()}
    assert "service" in columns
    assert "external_id" in columns
    assert "atlas_type" in columns
    assert "atlas_id" in columns
    assert "metadata" in columns
