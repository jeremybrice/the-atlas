# tests/unit/memory/test_procedural.py
import pytest
from atlas.memory.procedural import ProceduralMemoryStore
from atlas.memory.store import DatabaseStore
from atlas.contracts.types import Procedure


@pytest.fixture
async def proc_store(tmp_path):
    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()
    store = ProceduralMemoryStore(db)
    await store.initialize()
    yield store
    await db.close()


async def test_store_and_retrieve(proc_store):
    proc = Procedure(
        name="run-tests",
        description="Run pytest after source change",
        trigger_pattern="filesystem:*.py",
        steps=[{"skill": "shell.execute", "params": {"command": "pytest"}}],
    )
    proc_id = await proc_store.store(proc)
    retrieved = await proc_store.get(proc_id)
    assert retrieved is not None
    assert retrieved.name == "run-tests"
    assert len(retrieved.steps) == 1


async def test_search_by_trigger(proc_store):
    await proc_store.store(Procedure(
        name="test-py", description="test", trigger_pattern="filesystem:*.py",
        steps=[{"skill": "shell.execute", "params": {"command": "pytest"}}],
    ))
    await proc_store.store(Procedure(
        name="lint-js", description="lint", trigger_pattern="filesystem:*.js",
        steps=[{"skill": "shell.execute", "params": {"command": "eslint"}}],
    ))
    results = await proc_store.search_by_trigger("filesystem:*.py")
    assert len(results) == 1
    assert results[0].name == "test-py"


async def test_update_success_rate(proc_store):
    proc = Procedure(
        name="test", description="test", trigger_pattern="*",
        steps=[], success_rate=0.0, use_count=0,
    )
    proc_id = await proc_store.store(proc)
    await proc_store.record_outcome(proc_id, success=True)
    await proc_store.record_outcome(proc_id, success=False)
    updated = await proc_store.get(proc_id)
    assert updated.use_count == 2
    assert updated.success_rate == 0.5
