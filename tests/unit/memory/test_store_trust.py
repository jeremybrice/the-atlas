import pytest
from atlas.memory.store import DatabaseStore


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


async def test_trust_records_table_exists(db):
    cursor = await db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='trust_records'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "trust_records"


async def test_trust_records_columns(db):
    cursor = await db.db.execute("PRAGMA table_info(trust_records)")
    columns = {row[1] for row in await cursor.fetchall()}
    assert "skill_id" in columns
    assert "successes" in columns
    assert "failures" in columns
    assert "consecutive_successes" in columns
    assert "total_invocations" in columns
    assert "autonomy_override" in columns
    assert "updated_at" in columns
