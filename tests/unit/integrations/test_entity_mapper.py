import pytest
from atlas.integrations.entity_mapper import EntityMapper
from atlas.memory.store import DatabaseStore


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def mapper(db):
    return EntityMapper(db=db)


async def test_link_and_get_atlas_id(mapper):
    await mapper.link("github", "PR-123", "mission", "mission-abc")
    result = await mapper.get_atlas_id("github", "PR-123")
    assert result == ("mission", "mission-abc")


async def test_get_external_id(mapper):
    await mapper.link("github", "ISSUE-456", "task", "task-xyz")
    result = await mapper.get_external_id("github", "task", "task-xyz")
    assert result == "ISSUE-456"


async def test_get_atlas_id_not_found(mapper):
    result = await mapper.get_atlas_id("github", "nonexistent")
    assert result is None


async def test_get_external_id_not_found(mapper):
    result = await mapper.get_external_id("github", "mission", "nonexistent")
    assert result is None


async def test_unlink(mapper):
    await mapper.link("github", "PR-123", "mission", "mission-abc")
    await mapper.unlink("github", "PR-123")
    result = await mapper.get_atlas_id("github", "PR-123")
    assert result is None


async def test_link_with_metadata(mapper):
    await mapper.link(
        "github", "PR-123", "mission", "m-1", metadata={"repo": "owner/repo"}
    )
    result = await mapper.get_atlas_id("github", "PR-123")
    assert result == ("mission", "m-1")
