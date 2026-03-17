# Phase 3 Stage D1 — Code Review Fixes

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 2 issues identified in the PR #6 code review: migration marking complete on API failure, and hardcoded vault passphrase making vector search non-functional.

**Architecture:** Task 1 fixes migration to only mark complete when embeddings were actually stored (or no episodes need embedding). Task 2 replaces the hardcoded vault passphrase with environment variable `VOYAGE_API_KEY` as the primary key source, falling back to vault with a configurable passphrase.

**Tech Stack:** Python 3.12+, asyncio, aiosqlite, pytest

---

### Task 1: Fix migration marking complete on embed_batch failure

**Files:**
- Modify: `src/atlas/memory/migration.py:62-72`
- Modify: `tests/unit/memory/test_migration.py:64-71`

**Step 1: Write the failing test**

Add to `tests/unit/memory/test_migration.py`:

```python
async def test_migration_does_not_mark_complete_on_api_failure(migration_deps):
    """If embed_batch returns [] (API failure), migration should NOT mark complete."""
    db, episodic, vector_store, mock_provider = migration_deps

    await episodic.record(Episode(trigger="goal one", outcome="done"))
    mock_provider.embed_batch.return_value = []  # API failure

    migration = VectorMigration(db, episodic, vector_store, mock_provider)
    count = await migration.run()
    assert count == 0
    assert await migration.is_complete() is False  # should NOT be marked complete
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/unit/memory/test_migration.py::test_migration_does_not_mark_complete_on_api_failure -v`
Expected: FAIL — `assert await migration.is_complete() is False` fails because `_mark_complete()` is called unconditionally.

**Step 3: Fix the migration logic**

In `src/atlas/memory/migration.py`, change lines 62-72 from:

```python
        # Batch embed
        texts = [self._provider.compose_episode_text(ep) for ep in unembedded]
        embeddings = self._provider.embed_batch(texts)

        if embeddings:
            ids = [ep.episode_id for ep in unembedded[: len(embeddings)]]
            await self._vector_store.store_batch(ids, embeddings)
            logger.info("Migrated %d episodes to vector store", len(embeddings))

        await self._mark_complete()
        return len(embeddings)
```

to:

```python
        # Batch embed
        texts = [self._provider.compose_episode_text(ep) for ep in unembedded]
        embeddings = self._provider.embed_batch(texts)

        if not embeddings:
            logger.warning("Embedding API returned no results — migration will retry on next startup")
            return 0

        ids = [ep.episode_id for ep in unembedded[: len(embeddings)]]
        await self._vector_store.store_batch(ids, embeddings)
        logger.info("Migrated %d episodes to vector store", len(embeddings))

        await self._mark_complete()
        return len(embeddings)
```

**Step 4: Fix the existing test that validated the buggy behavior**

In `tests/unit/memory/test_migration.py`, update `test_migration_marks_complete` (lines 64-71). The existing test sets `embed_batch.return_value = []` and asserts `is_complete() is True` — this is the buggy behavior. Change it to test the correct case where migration actually embeds episodes:

```python
async def test_migration_marks_complete(migration_deps):
    db, episodic, vector_store, mock_provider = migration_deps

    await episodic.record(Episode(trigger="goal one", outcome="done"))

    mock_provider.embed_batch.return_value = [
        np.array([0.1, 0.2, 0.3], dtype=np.float32),
    ]

    migration = VectorMigration(db, episodic, vector_store, mock_provider)
    await migration.run()

    assert await migration.is_complete() is True
```

**Step 5: Run tests**

Run: `source .venv/bin/activate && pytest tests/unit/memory/test_migration.py -v`
Expected: ALL PASS

**Step 6: Run full test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: ALL PASS (272 tests)

**Step 7: Commit**

```bash
git add src/atlas/memory/migration.py tests/unit/memory/test_migration.py
git commit -m "fix: do not mark migration complete when embed_batch fails"
```

---

### Task 2: Replace hardcoded vault passphrase with environment variable

**Files:**
- Modify: `src/atlas/cli.py:165-195`

**Step 1: Update the vector search initialization to use environment variable**

In `src/atlas/cli.py`, change lines 165-195 from:

```python
    if config.memory.vector_search.enabled:
        try:
            from atlas.integrations.vault import CredentialVault
            from atlas.memory.embeddings import EmbeddingProvider
            from atlas.memory.migration import VectorMigration
            from atlas.memory.vector_store import VectorStore

            vault = await CredentialVault.create(db=db, passphrase="atlas-default")
            api_key = await vault.get("voyage", "api_key")

            embedding_provider = EmbeddingProvider(
                api_key=api_key, model=config.memory.vector_search.model,
            )
```

to:

```python
    if config.memory.vector_search.enabled:
        try:
            import os

            from atlas.memory.embeddings import EmbeddingProvider
            from atlas.memory.migration import VectorMigration
            from atlas.memory.vector_store import VectorStore

            api_key = os.environ.get("VOYAGE_API_KEY")
            if not api_key:
                raise ValueError("VOYAGE_API_KEY environment variable not set")

            embedding_provider = EmbeddingProvider(
                api_key=api_key, model=config.memory.vector_search.model,
            )
```

**Step 2: Run tests**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: ALL PASS

**Step 3: Run linter**

Run: `source .venv/bin/activate && ruff check src/atlas/cli.py`
Expected: No errors

**Step 4: Commit**

```bash
git add src/atlas/cli.py
git commit -m "fix: use VOYAGE_API_KEY env var instead of hardcoded vault passphrase"
```

---

## Verification

After both tasks, run:

```bash
source .venv/bin/activate && pytest tests/ -v && ruff check src/ tests/
```

Expected: All tests pass, no lint errors.
