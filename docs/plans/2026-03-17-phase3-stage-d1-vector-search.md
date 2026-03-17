# Phase 3 Stage D1: Vector Search Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add semantic vector search to ATLAS's episodic memory using Voyage AI embeddings, with hybrid keyword+semantic retrieval, and wire context assembly into the execution loop so past episodes inform planning.

**Architecture:** Three new components: `EmbeddingProvider` wraps the Voyage AI API, `VectorStore` persists embeddings as BLOBs in SQLite and computes cosine similarity via numpy, and a hybrid retrieval layer in `ContextAssembler` merges FTS5 keyword and vector similarity scores. The execution loop calls `ContextAssembler.assemble()` before task planning, passing the resulting `ContextBundle` to the Claude bridge. On first run, a batch migration embeds all existing episodes.

**Tech Stack:** Python 3.12, voyageai SDK, numpy, aiosqlite (existing), pytest

---

### Task 1: Add voyageai and numpy dependencies

**Files:**
- Modify: `pyproject.toml:10-19`

**Step 1: Add dependencies to pyproject.toml**

In `pyproject.toml`, add `voyageai` and `numpy` to the `dependencies` list (lines 10-19):

```python
dependencies = [
    "click>=8.1",
    "aiosqlite>=0.20",
    "pyyaml>=6.0",
    "anthropic>=0.42",
    "httpx>=0.27",
    "watchdog>=4.0",
    "cryptography>=43.0",
    "aiohttp>=3.10",
    "voyageai>=0.3",
    "numpy>=1.26",
]
```

**Step 2: Install**

Run: `source .venv/bin/activate && pip install -e ".[dev]"`
Expected: Install succeeds, `voyageai` and `numpy` importable.

**Step 3: Verify imports**

Run: `source .venv/bin/activate && python -c "import voyageai; import numpy; print('ok')"`
Expected: `ok`

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add voyageai and numpy dependencies for vector search"
```

---

### Task 2: Add VectorSearchConfig and episode_embeddings/metadata tables

**Files:**
- Modify: `src/atlas/config.py:32-36`
- Modify: `config/default.yaml:26-30`
- Modify: `src/atlas/memory/store.py:30-138`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/memory/test_episodic.py`

**Step 1: Write the failing test for config**

Add to `tests/unit/test_config.py`:

```python
def test_vector_search_config_defaults():
    from atlas.config import VectorSearchConfig
    cfg = VectorSearchConfig()
    assert cfg.enabled is False
    assert cfg.model == "voyage-3-lite"
    assert cfg.semantic_weight == 0.6
    assert cfg.keyword_weight == 0.4
    assert cfg.search_limit == 50
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/unit/test_config.py::test_vector_search_config_defaults -v`
Expected: FAIL — `VectorSearchConfig` not found.

**Step 3: Add VectorSearchConfig dataclass**

In `src/atlas/config.py`, add after `MemoryConfig` (after line 36):

```python
@dataclass
class VectorSearchConfig:
    enabled: bool = False
    model: str = "voyage-3-lite"
    semantic_weight: float = 0.6
    keyword_weight: float = 0.4
    search_limit: int = 50
```

Add `vector_search: VectorSearchConfig = field(default_factory=VectorSearchConfig)` to `MemoryConfig`:

```python
@dataclass
class MemoryConfig:
    working_memory_max_keys: int = 100
    episode_retention_days: int = 90
    context_default_token_budget: int = 4000
    pattern_extraction_interval_minutes: int = 30
    vector_search: VectorSearchConfig = field(default_factory=VectorSearchConfig)
```

Add `"vector_search": VectorSearchConfig` to `_SECTION_MAP` is NOT needed — it's nested under `memory`. But update `_merge_into_dataclass` handling: in `load_config`, the `memory` section's `vector_search` sub-dict needs to be converted. Update `_merge_into_dataclass` to handle nested dataclasses:

Actually, since `_merge_into_dataclass` only handles flat dicts, update `load_config` to handle `vector_search` specifically. Instead, the simpler approach: in `_merge_into_dataclass`, check if a field is a dataclass and recurse:

```python
def _merge_into_dataclass(dc_class, data: dict):
    """Create a dataclass instance from a dict, ignoring unknown keys."""
    import dataclasses
    valid_fields = {f.name: f for f in dc_class.__dataclass_fields__.values()}
    filtered = {}
    for k, v in data.items():
        if k in valid_fields:
            field_type = valid_fields[k].type
            # Handle nested dataclasses
            if isinstance(v, dict) and isinstance(field_type, type) and dataclasses.is_dataclass(field_type):
                filtered[k] = _merge_into_dataclass(field_type, v)
            else:
                filtered[k] = v
    return dc_class(**filtered)
```

Wait — `field.type` is a string due to `from __future__ import annotations`. The config module does NOT use `from __future__ import annotations`. Check: `src/atlas/config.py` line 1 starts with `"""Structured configuration...`. No `__future__` import. So `field.type` will be the actual type at runtime for simple cases. But `VectorSearchConfig` is defined before `MemoryConfig`, so the forward reference will resolve. However, `dc_class.__dataclass_fields__` stores types as the actual type objects when no `__future__` annotations is used. Let's verify with a simpler approach:

```python
def _merge_into_dataclass(dc_class, data: dict):
    """Create a dataclass instance from a dict, ignoring unknown keys."""
    import dataclasses
    fields = {f.name: f for f in dataclasses.fields(dc_class)}
    filtered = {}
    for k, v in data.items():
        if k in fields:
            ft = fields[k].type
            if isinstance(v, dict) and dataclasses.is_dataclass(ft):
                filtered[k] = _merge_into_dataclass(ft, v)
            else:
                filtered[k] = v
    return dc_class(**filtered)
```

**Step 4: Add vector_search section to default.yaml**

In `config/default.yaml`, update the `memory` section (lines 26-30):

```yaml
memory:
  working_memory_max_keys: 100
  episode_retention_days: 90
  context_default_token_budget: 4000
  pattern_extraction_interval_minutes: 30
  vector_search:
    enabled: false
    model: "voyage-3-lite"
    semantic_weight: 0.6
    keyword_weight: 0.4
    search_limit: 50
```

**Step 5: Run config test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/unit/test_config.py -v`
Expected: ALL PASS

**Step 6: Write test for new tables**

Add to `tests/unit/memory/test_episodic.py`:

```python
async def test_episode_embeddings_table_exists(episodic_store: EpisodicMemoryStore):
    """The episode_embeddings table should be created by initialize()."""
    cursor = await episodic_store._db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='episode_embeddings'"
    )
    row = await cursor.fetchone()
    assert row is not None


async def test_metadata_table_exists(episodic_store: EpisodicMemoryStore):
    """The metadata table should be created by initialize()."""
    cursor = await episodic_store._db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'"
    )
    row = await cursor.fetchone()
    assert row is not None
```

**Step 7: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/memory/test_episodic.py::test_episode_embeddings_table_exists tests/unit/memory/test_episodic.py::test_metadata_table_exists -v`
Expected: FAIL — tables don't exist.

**Step 8: Add tables to DatabaseStore schema**

In `src/atlas/memory/store.py`, add before the closing `""")` of `_create_tables` (before line 138):

```sql
            CREATE TABLE IF NOT EXISTS episode_embeddings (
                episode_id TEXT PRIMARY KEY REFERENCES episodes(episode_id),
                embedding BLOB NOT NULL,
                model TEXT NOT NULL,
                dimensions INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
```

**Step 9: Run all tests**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: ALL PASS

**Step 10: Commit**

```bash
git add src/atlas/config.py config/default.yaml src/atlas/memory/store.py tests/unit/test_config.py tests/unit/memory/test_episodic.py
git commit -m "feat: add VectorSearchConfig, episode_embeddings and metadata tables"
```

---

### Task 3: Implement EmbeddingProvider

**Files:**
- Create: `src/atlas/memory/embeddings.py`
- Test: `tests/unit/memory/test_embeddings.py`

**Step 1: Write the failing tests**

Create `tests/unit/memory/test_embeddings.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from atlas.memory.embeddings import EmbeddingProvider


@pytest.fixture
def mock_voyage_client():
    client = MagicMock()
    # voyage client's embed method returns an object with .embeddings attribute
    result = MagicMock()
    result.embeddings = [[0.1, 0.2, 0.3] * 341 + [0.1]]  # 1024 dims
    client.embed = MagicMock(return_value=result)
    return client


@pytest.fixture
def provider(mock_voyage_client):
    with patch("atlas.memory.embeddings.voyageai") as mock_voyageai:
        mock_voyageai.Client.return_value = mock_voyage_client
        p = EmbeddingProvider(api_key="test-key", model="voyage-3-lite")
        yield p


def test_embed_returns_numpy_array(provider, mock_voyage_client):
    result = provider.embed("hello world")
    assert isinstance(result, np.ndarray)
    assert result.dtype == np.float32
    mock_voyage_client.embed.assert_called_once_with(
        ["hello world"], model="voyage-3-lite", input_type="document",
    )


def test_embed_batch_returns_list_of_arrays(provider, mock_voyage_client):
    mock_result = MagicMock()
    mock_result.embeddings = [
        [0.1, 0.2, 0.3] * 341 + [0.1],
        [0.4, 0.5, 0.6] * 341 + [0.4],
    ]
    mock_voyage_client.embed.return_value = mock_result

    results = provider.embed_batch(["text one", "text two"])
    assert len(results) == 2
    assert all(isinstance(r, np.ndarray) for r in results)
    assert all(r.dtype == np.float32 for r in results)


def test_embed_query_uses_query_input_type(provider, mock_voyage_client):
    provider.embed_query("search for something")
    mock_voyage_client.embed.assert_called_once_with(
        ["search for something"], model="voyage-3-lite", input_type="query",
    )


def test_compose_episode_text(provider):
    from atlas.contracts.types import Episode
    episode = Episode(
        trigger="deploy the app",
        plan="run deploy script",
        outcome="deployment succeeded",
        lessons=["always check CI first"],
    )
    text = provider.compose_episode_text(episode)
    assert "deploy the app" in text
    assert "run deploy script" in text
    assert "deployment succeeded" in text
    assert "always check CI first" in text


def test_embed_returns_none_on_api_error(provider, mock_voyage_client):
    mock_voyage_client.embed.side_effect = Exception("API timeout")
    result = provider.embed("hello")
    assert result is None


def test_embed_batch_returns_empty_on_api_error(provider, mock_voyage_client):
    mock_voyage_client.embed.side_effect = Exception("API timeout")
    results = provider.embed_batch(["text"])
    assert results == []
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/memory/test_embeddings.py -v`
Expected: FAIL — module not found.

**Step 3: Implement EmbeddingProvider**

Create `src/atlas/memory/embeddings.py`:

```python
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
        self._client = voyageai.Client(api_key=api_key)

    def embed(self, text: str) -> np.ndarray | None:
        """Embed a single text for storage (document input type). Returns None on error."""
        try:
            result = self._client.embed([text], model=self._model, input_type="document")
            return np.array(result.embeddings[0], dtype=np.float32)
        except Exception as e:
            logger.warning("Embedding failed: %s", e)
            return None

    def embed_query(self, text: str) -> np.ndarray | None:
        """Embed a query for search (query input type). Returns None on error."""
        try:
            result = self._client.embed([text], model=self._model, input_type="query")
            return np.array(result.embeddings[0], dtype=np.float32)
        except Exception as e:
            logger.warning("Query embedding failed: %s", e)
            return None

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        """Embed multiple texts for storage. Returns empty list on error."""
        try:
            result = self._client.embed(texts, model=self._model, input_type="document")
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
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/unit/memory/test_embeddings.py -v`
Expected: ALL PASS

**Step 5: Run linter**

Run: `source .venv/bin/activate && ruff check src/atlas/memory/embeddings.py tests/unit/memory/test_embeddings.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/atlas/memory/embeddings.py tests/unit/memory/test_embeddings.py
git commit -m "feat: implement EmbeddingProvider wrapping Voyage AI"
```

---

### Task 4: Implement VectorStore

**Files:**
- Create: `src/atlas/memory/vector_store.py`
- Test: `tests/unit/memory/test_vector_store.py`

**Step 1: Write the failing tests**

Create `tests/unit/memory/test_vector_store.py`:

```python
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
    await vector_store.store("ep-different", np.array([0.0, 0.0, 1.0], dtype=np.float32))

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
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/memory/test_vector_store.py -v`
Expected: FAIL — module not found.

**Step 3: Implement VectorStore**

Create `src/atlas/memory/vector_store.py`:

```python
"""Vector Store — SQLite-backed embedding storage with cosine similarity search."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np

from atlas.memory.store import DatabaseStore

logger = logging.getLogger(__name__)


class VectorStore:
    """Stores and searches embeddings using SQLite BLOBs and numpy cosine similarity."""

    def __init__(self, db: DatabaseStore, model: str = "voyage-3-lite"):
        self._db = db
        self._model = model

    async def store(self, episode_id: str, embedding: np.ndarray) -> None:
        """Store an embedding for an episode."""
        await self._db.db.execute(
            """INSERT OR REPLACE INTO episode_embeddings
               (episode_id, embedding, model, dimensions, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                episode_id,
                embedding.tobytes(),
                self._model,
                len(embedding),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await self._db.db.commit()

    async def store_batch(self, episode_ids: list[str], embeddings: list[np.ndarray]) -> None:
        """Store embeddings for multiple episodes."""
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (eid, emb.tobytes(), self._model, len(emb), now)
            for eid, emb in zip(episode_ids, embeddings)
        ]
        await self._db.db.executemany(
            """INSERT OR REPLACE INTO episode_embeddings
               (episode_id, embedding, model, dimensions, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            rows,
        )
        await self._db.db.commit()

    async def get(self, episode_id: str) -> np.ndarray | None:
        """Retrieve an embedding by episode ID."""
        cursor = await self._db.db.execute(
            "SELECT embedding, dimensions FROM episode_embeddings WHERE episode_id = ?",
            (episode_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return np.frombuffer(row[0], dtype=np.float32).copy()

    async def search(self, query_embedding: np.ndarray, limit: int = 50) -> list[tuple[str, float]]:
        """Search for similar episodes by cosine similarity.

        Returns list of (episode_id, similarity_score) sorted by score descending.
        """
        cursor = await self._db.db.execute(
            "SELECT episode_id, embedding FROM episode_embeddings"
        )
        rows = await cursor.fetchall()

        if not rows:
            return []

        # Compute cosine similarity for all stored embeddings
        query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-10)
        scored = []
        for episode_id, blob in rows:
            stored = np.frombuffer(blob, dtype=np.float32)
            stored_norm = stored / (np.linalg.norm(stored) + 1e-10)
            similarity = float(np.dot(query_norm, stored_norm))
            # Clamp to [0, 1] range
            similarity = max(0.0, min(1.0, similarity))
            scored.append((episode_id, similarity))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def has_embedding(self, episode_id: str) -> bool:
        """Check if an episode has a stored embedding."""
        cursor = await self._db.db.execute(
            "SELECT 1 FROM episode_embeddings WHERE episode_id = ?",
            (episode_id,),
        )
        return await cursor.fetchone() is not None

    async def count(self) -> int:
        """Return the number of stored embeddings."""
        cursor = await self._db.db.execute("SELECT COUNT(*) FROM episode_embeddings")
        row = await cursor.fetchone()
        return row[0]
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/unit/memory/test_vector_store.py -v`
Expected: ALL PASS

**Step 5: Run linter**

Run: `source .venv/bin/activate && ruff check src/atlas/memory/vector_store.py tests/unit/memory/test_vector_store.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/atlas/memory/vector_store.py tests/unit/memory/test_vector_store.py
git commit -m "feat: implement VectorStore with SQLite BLOBs and numpy cosine similarity"
```

---

### Task 5: Add hybrid retrieval to ContextAssembler

**Files:**
- Modify: `src/atlas/memory/retrieval.py:1-116`
- Test: `tests/unit/memory/test_retrieval.py`

**Step 1: Write the failing tests**

Add to `tests/unit/memory/test_retrieval.py`:

```python
def test_hybrid_merge_both_sets():
    """Episodes in both keyword and semantic results get blended scores."""
    assembler = ContextAssembler()
    keyword_scores = {"ep-1": 0.8, "ep-2": 0.5}
    semantic_scores = {"ep-1": 0.9, "ep-3": 0.7}

    merged = assembler.merge_scores(
        keyword_scores, semantic_scores,
        semantic_weight=0.6, keyword_weight=0.4,
    )

    # ep-1 in both: 0.6*0.9 + 0.4*0.8 = 0.86
    assert abs(merged["ep-1"] - 0.86) < 0.01
    # ep-2 keyword only: 0.4*0.5 = 0.2
    assert abs(merged["ep-2"] - 0.2) < 0.01
    # ep-3 semantic only: 0.6*0.7 = 0.42
    assert abs(merged["ep-3"] - 0.42) < 0.01


def test_hybrid_merge_empty_semantic():
    """When semantic results are empty, keyword scores are scaled by keyword_weight."""
    assembler = ContextAssembler()
    keyword_scores = {"ep-1": 1.0}
    semantic_scores = {}

    merged = assembler.merge_scores(
        keyword_scores, semantic_scores,
        semantic_weight=0.6, keyword_weight=0.4,
    )
    assert abs(merged["ep-1"] - 0.4) < 0.01


def test_hybrid_merge_empty_keyword():
    """When keyword results are empty, semantic scores are scaled by semantic_weight."""
    assembler = ContextAssembler()
    keyword_scores = {}
    semantic_scores = {"ep-1": 1.0}

    merged = assembler.merge_scores(
        keyword_scores, semantic_scores,
        semantic_weight=0.6, keyword_weight=0.4,
    )
    assert abs(merged["ep-1"] - 0.6) < 0.01


def test_rank_by_merged_scores():
    """assemble_hybrid should rank episodes by merged score, not recency."""
    assembler = ContextAssembler()
    ep_high = Episode(episode_id="ep-high", trigger="highly relevant", outcome="success")
    ep_low = Episode(episode_id="ep-low", trigger="less relevant", outcome="success")
    episodes_by_id = {"ep-high": ep_high, "ep-low": ep_low}
    merged_scores = {"ep-high": 0.9, "ep-low": 0.3}

    query = ContextQuery(purpose="planning", task_description="test", token_budget=4000)
    bundle = assembler.assemble_ranked(query, episodes_by_id, merged_scores)

    assert len(bundle.contents) == 2
    assert bundle.contents[0]["source"] == "highly relevant"
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/memory/test_retrieval.py::test_hybrid_merge_both_sets -v`
Expected: FAIL — `merge_scores` not found.

**Step 3: Add merge_scores and assemble_ranked to ContextAssembler**

In `src/atlas/memory/retrieval.py`, add the following methods to `ContextAssembler`:

```python
    def merge_scores(
        self,
        keyword_scores: dict[str, float],
        semantic_scores: dict[str, float],
        semantic_weight: float = 0.6,
        keyword_weight: float = 0.4,
    ) -> dict[str, float]:
        """Merge keyword and semantic scores into a single ranked score per episode."""
        all_ids = set(keyword_scores) | set(semantic_scores)
        merged = {}
        for eid in all_ids:
            kw = keyword_scores.get(eid, 0.0) * keyword_weight
            sem = semantic_scores.get(eid, 0.0) * semantic_weight
            merged[eid] = kw + sem
        return merged

    def assemble_ranked(
        self,
        query: ContextQuery,
        episodes_by_id: dict[str, Episode],
        scores: dict[str, float],
        procedures: list[Procedure] | None = None,
    ) -> ContextBundle:
        """Assemble context from episodes ranked by pre-computed scores."""
        # Sort episode IDs by score descending
        ranked_ids = sorted(scores, key=scores.get, reverse=True)
        ranked_episodes = [episodes_by_id[eid] for eid in ranked_ids if eid in episodes_by_id]
        return self._assemble_episodes(query, ranked_episodes, procedures)
```

Also refactor the existing `assemble` method to share the core assembly logic. Extract the loop from `assemble` into a private `_assemble_episodes`:

```python
    def assemble(
        self,
        query: ContextQuery,
        episodes: list[Episode],
        procedures: list[Procedure] | None = None,
    ) -> ContextBundle:
        if not episodes and not procedures:
            return ContextBundle(budget_tokens=query.token_budget)

        sorted_episodes = self._sort_for_purpose(query.purpose, episodes)
        return self._assemble_episodes(query, sorted_episodes, procedures)

    def _assemble_episodes(
        self,
        query: ContextQuery,
        episodes: list[Episode],
        procedures: list[Procedure] | None = None,
    ) -> ContextBundle:
        """Core assembly logic shared by assemble() and assemble_ranked()."""
        contents: list[dict] = []
        total_tokens = 0

        # For planning purpose, include procedures first
        if query.purpose == "planning" and procedures:
            for proc in procedures:
                text = self._procedure_to_text(proc)
                tokens = self.estimate_tokens(text)
                if total_tokens + tokens > query.token_budget:
                    break
                contents.append({
                    "source": f"procedure:{proc.name}",
                    "text": text,
                    "tokens": tokens,
                    "truncated": False,
                })
                total_tokens += tokens

        for episode in episodes:
            text = self._episode_to_text(episode)
            tokens = self.estimate_tokens(text)

            if total_tokens + tokens > query.token_budget:
                remaining = query.token_budget - total_tokens
                if remaining > 20:
                    truncated = text[: remaining * self.CHARS_PER_TOKEN]
                    contents.append({
                        "source": episode.trigger,
                        "text": truncated,
                        "tokens": remaining,
                        "truncated": True,
                    })
                    total_tokens += remaining
                break

            contents.append({
                "source": episode.trigger,
                "text": text,
                "tokens": tokens,
                "truncated": False,
            })
            total_tokens += tokens

        return ContextBundle(
            contents=contents,
            total_tokens=total_tokens,
            budget_tokens=query.token_budget,
        )
```

**Step 4: Run all retrieval tests**

Run: `source .venv/bin/activate && pytest tests/unit/memory/test_retrieval.py -v`
Expected: ALL PASS (existing + new)

**Step 5: Run linter**

Run: `source .venv/bin/activate && ruff check src/atlas/memory/retrieval.py tests/unit/memory/test_retrieval.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/atlas/memory/retrieval.py tests/unit/memory/test_retrieval.py
git commit -m "feat: add hybrid scoring and ranked assembly to ContextAssembler"
```

---

### Task 6: Add FTS5 scoring to EpisodicMemoryStore

**Files:**
- Modify: `src/atlas/memory/episodic.py:50-59`
- Modify: `src/atlas/memory/store.py:56-59` (FTS5 trigger)
- Test: `tests/unit/memory/test_episodic.py`

**Step 1: Write the failing test**

Add to `tests/unit/memory/test_episodic.py`:

```python
async def test_search_scored_returns_scores(episodic_store: EpisodicMemoryStore):
    await episodic_store.record(Episode(
        trigger="deploy the application to production",
        outcome="deployment succeeded",
    ))
    await episodic_store.record(Episode(
        trigger="fix the login bug in auth module",
        outcome="bug fixed",
    ))
    results = await episodic_store.search_scored("deploy", limit=10)
    assert len(results) >= 1
    # Returns list of (episode_id, score) tuples
    episode_id, score = results[0]
    assert isinstance(episode_id, str)
    assert isinstance(score, float)
    assert score > 0.0
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/unit/memory/test_episodic.py::test_search_scored_returns_scores -v`
Expected: FAIL — `search_scored` not found.

**Step 3: Add search_scored method**

In `src/atlas/memory/episodic.py`, add after the `search` method (after line 59):

```python
    async def search_scored(self, text_query: str, limit: int = 20) -> list[tuple[str, float]]:
        """Search episodes and return (episode_id, relevance_score) tuples.

        Scores are normalized FTS5 rank values in [0, 1] range.
        """
        cursor = await self._db.db.execute(
            """SELECT e.episode_id, rank
               FROM episodes e
               JOIN episodes_fts fts ON e.episode_id = fts.episode_id
               WHERE episodes_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (text_query, limit),
        )
        rows = await cursor.fetchall()
        if not rows:
            return []

        # FTS5 rank is negative (more negative = more relevant)
        # Normalize to [0, 1] where 1 = most relevant
        raw_scores = [(r[0], -r[1]) for r in rows]  # flip sign
        max_score = max(s for _, s in raw_scores) if raw_scores else 1.0
        if max_score == 0:
            max_score = 1.0
        return [(eid, score / max_score) for eid, score in raw_scores]
```

**Step 4: Update FTS5 trigger to include lessons**

In `src/atlas/memory/store.py`, update the FTS5 virtual table and trigger.

Change the FTS5 table (lines 47-54):

```sql
            CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
                episode_id,
                trigger_text,
                plan,
                outcome,
                lessons,
                content=episodes,
                content_rowid=rowid
            );
```

Change the trigger (lines 56-59):

```sql
            CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
                INSERT INTO episodes_fts(episode_id, trigger_text, plan, outcome, lessons)
                VALUES (new.episode_id, new.trigger_text, new.plan, new.outcome, new.lessons);
            END;
```

**Step 5: Run tests**

Run: `source .venv/bin/activate && pytest tests/unit/memory/test_episodic.py -v`
Expected: ALL PASS

**Step 6: Run linter**

Run: `source .venv/bin/activate && ruff check src/atlas/memory/episodic.py src/atlas/memory/store.py`
Expected: No errors

**Step 7: Commit**

```bash
git add src/atlas/memory/episodic.py src/atlas/memory/store.py tests/unit/memory/test_episodic.py
git commit -m "feat: add scored FTS5 search and include lessons in FTS5 index"
```

---

### Task 7: Embed episodes on record and add migration logic

**Files:**
- Modify: `src/atlas/memory/episodic.py`
- Create: `src/atlas/memory/migration.py`
- Test: `tests/unit/memory/test_embeddings.py` (add integration-style test)
- Test: `tests/unit/memory/test_migration.py`

**Step 1: Write the failing test for embed-on-record**

Add to `tests/unit/memory/test_embeddings.py`:

```python
async def test_episodic_store_embeds_on_record(tmp_path):
    """When an embedding provider is set, recording an episode also stores its embedding."""
    from atlas.memory.store import DatabaseStore
    from atlas.memory.episodic import EpisodicMemoryStore
    from atlas.memory.vector_store import VectorStore
    from atlas.contracts.types import Episode

    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()

    mock_provider = MagicMock()
    mock_provider.compose_episode_text.return_value = "test text"
    mock_provider.embed.return_value = np.array([0.1, 0.2, 0.3], dtype=np.float32)

    vector_store = VectorStore(db, model="voyage-3-lite")
    store = EpisodicMemoryStore(db, embedding_provider=mock_provider, vector_store=vector_store)

    episode = Episode(trigger="test goal", outcome="done")
    await store.record(episode)

    # Verify embedding was stored
    result = await vector_store.get(episode.episode_id)
    assert result is not None
    await db.close()


async def test_episodic_store_records_without_provider(tmp_path):
    """Recording without an embedding provider should still work (no vector stored)."""
    from atlas.memory.store import DatabaseStore
    from atlas.memory.episodic import EpisodicMemoryStore
    from atlas.memory.vector_store import VectorStore
    from atlas.contracts.types import Episode

    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()

    store = EpisodicMemoryStore(db)
    episode = Episode(trigger="test goal", outcome="done")
    episode_id = await store.record(episode)
    assert episode_id == episode.episode_id

    vector_store = VectorStore(db)
    assert await vector_store.has_embedding(episode.episode_id) is False
    await db.close()
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/memory/test_embeddings.py::test_episodic_store_embeds_on_record -v`
Expected: FAIL — `EpisodicMemoryStore` doesn't accept `embedding_provider`.

**Step 3: Update EpisodicMemoryStore to accept optional embedding components**

In `src/atlas/memory/episodic.py`, modify the constructor and `record` method:

```python
"""Episodic Memory — chronological record of agent actions and observations."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from atlas.contracts.types import Episode, EpisodeType
from atlas.memory.store import DatabaseStore

if TYPE_CHECKING:
    from atlas.memory.embeddings import EmbeddingProvider
    from atlas.memory.vector_store import VectorStore

logger = logging.getLogger(__name__)


class EpisodicMemoryStore:
    """SQLite-backed episodic memory with FTS5 full-text search."""

    def __init__(
        self,
        db: DatabaseStore,
        embedding_provider: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
    ):
        self._db = db
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store
```

Update `record` to embed after insert:

```python
    async def record(self, episode: Episode) -> str:
        await self._db.db.execute(
            """INSERT INTO episodes
               (episode_id, timestamp, episode_type, trigger_text, plan,
                actions, outcome, lessons, mission_id, task_id, tags, correlation_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                episode.episode_id,
                episode.timestamp.isoformat(),
                episode.episode_type.value,
                episode.trigger,
                episode.plan,
                json.dumps(episode.actions),
                episode.outcome,
                json.dumps(episode.lessons),
                episode.mission_id,
                episode.task_id,
                json.dumps(episode.tags),
                episode.correlation_id,
            ),
        )
        await self._db.db.commit()

        # Embed and store vector if provider is available
        if self._embedding_provider and self._vector_store:
            text = self._embedding_provider.compose_episode_text(episode)
            embedding = self._embedding_provider.embed(text)
            if embedding is not None:
                await self._vector_store.store(episode.episode_id, embedding)
            else:
                logger.warning("Failed to embed episode %s, will retry on migration", episode.episode_id)

        return episode.episode_id
```

**Step 4: Write migration test**

Create `tests/unit/memory/test_migration.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock

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
    mock_provider.embed_batch.return_value = [
        np.array([0.1, 0.2, 0.3], dtype=np.float32),
        np.array([0.4, 0.5, 0.6], dtype=np.float32),
    ]

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

    mock_provider.embed_batch.return_value = [
        np.array([0.4, 0.5, 0.6], dtype=np.float32),
    ]

    migration = VectorMigration(db, episodic, vector_store, mock_provider)
    count = await migration.run()
    assert count == 1  # only the un-embedded one


async def test_migration_marks_complete(migration_deps):
    db, episodic, vector_store, mock_provider = migration_deps
    mock_provider.embed_batch.return_value = []

    migration = VectorMigration(db, episodic, vector_store, mock_provider)
    await migration.run()

    assert await migration.is_complete() is True


async def test_migration_noop_if_already_complete(migration_deps):
    db, episodic, vector_store, mock_provider = migration_deps
    mock_provider.embed_batch.return_value = []

    migration = VectorMigration(db, episodic, vector_store, mock_provider)
    await migration.run()
    count = await migration.run()  # second run
    assert count == 0
```

**Step 5: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/memory/test_migration.py -v`
Expected: FAIL — `VectorMigration` not found.

**Step 6: Implement VectorMigration**

Create `src/atlas/memory/migration.py`:

```python
"""Vector Migration — batch-embeds existing episodes that lack embeddings."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from atlas.memory.embeddings import EmbeddingProvider
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.store import DatabaseStore
from atlas.memory.vector_store import VectorStore

logger = logging.getLogger(__name__)

MIGRATION_KEY = "vector_migration_complete"


class VectorMigration:
    """One-time migration: embeds all existing episodes without embeddings."""

    def __init__(
        self,
        db: DatabaseStore,
        episodic: EpisodicMemoryStore,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
    ):
        self._db = db
        self._episodic = episodic
        self._vector_store = vector_store
        self._provider = embedding_provider

    async def is_complete(self) -> bool:
        """Check if migration has already run."""
        cursor = await self._db.db.execute(
            "SELECT value FROM metadata WHERE key = ?", (MIGRATION_KEY,)
        )
        return await cursor.fetchone() is not None

    async def run(self) -> int:
        """Run migration. Returns count of newly embedded episodes."""
        if await self.is_complete():
            logger.info("Vector migration already complete, skipping")
            return 0

        # Get all episodes
        episodes = await self._episodic.query_recent(limit=100_000)
        if not episodes:
            await self._mark_complete()
            return 0

        # Filter out already-embedded episodes
        unembedded = []
        for ep in episodes:
            if not await self._vector_store.has_embedding(ep.episode_id):
                unembedded.append(ep)

        if not unembedded:
            await self._mark_complete()
            return 0

        # Batch embed
        texts = [self._provider.compose_episode_text(ep) for ep in unembedded]
        embeddings = self._provider.embed_batch(texts)

        if embeddings:
            ids = [ep.episode_id for ep in unembedded[: len(embeddings)]]
            await self._vector_store.store_batch(ids, embeddings)
            logger.info("Migrated %d episodes to vector store", len(embeddings))

        await self._mark_complete()
        return len(embeddings)

    async def _mark_complete(self) -> None:
        """Mark migration as complete in metadata table."""
        await self._db.db.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (MIGRATION_KEY, datetime.now(timezone.utc).isoformat()),
        )
        await self._db.db.commit()
```

**Step 7: Run all tests**

Run: `source .venv/bin/activate && pytest tests/unit/memory/ -v`
Expected: ALL PASS

**Step 8: Run linter**

Run: `source .venv/bin/activate && ruff check src/atlas/memory/ tests/unit/memory/`
Expected: No errors

**Step 9: Commit**

```bash
git add src/atlas/memory/episodic.py src/atlas/memory/migration.py tests/unit/memory/test_embeddings.py tests/unit/memory/test_migration.py
git commit -m "feat: embed episodes on record and add batch migration"
```

---

### Task 8: Wire ContextAssembler into ExecutionLoop

**Files:**
- Modify: `src/atlas/core/loop.py:52-78,79-96`
- Test: `tests/unit/core/test_loop_context.py`

**Step 1: Write the failing test**

Create `tests/unit/core/test_loop_context.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from atlas.contracts.types import (
    ClaudeResponse,
    ContextBundle,
    ContextQuery,
    Episode,
    EpisodeType,
    ExecutionContext,
    MissionStatus,
    PolicyDecision,
    SkillDescriptor,
    SkillResult,
)
from atlas.core.loop import ExecutionLoop
from atlas.core.missions import Mission
from atlas.core.tasks import Task
from atlas.memory.retrieval import ContextAssembler


@pytest.fixture
def mock_components():
    registry = MagicMock()
    registry.list_all.return_value = []
    registry.get.return_value = SkillDescriptor(
        skill_id="shell.execute", name="shell.execute", description="run shell"
    )

    runtime = MagicMock()
    runtime.invoke = AsyncMock(return_value=SkillResult(status="success", output="done"))

    env = MagicMock()
    env.claude_oneshot = AsyncMock(return_value=ClaudeResponse(content='{"tasks":[]}'))

    policy = MagicMock()
    policy.evaluate.return_value = PolicyDecision.ALLOW

    audit = MagicMock()
    audit.log = AsyncMock()

    approval = MagicMock()
    working = MagicMock()

    episodic = MagicMock()
    episodic.record = AsyncMock(return_value="ep-1")
    episodic.search_scored = AsyncMock(return_value=[])
    episodic.get_by_id = AsyncMock(return_value=None)

    return registry, runtime, env, policy, audit, approval, working, episodic


async def test_execution_loop_calls_context_assembler(mock_components):
    """When context_assembler is provided, it should be called before task execution."""
    registry, runtime, env, policy, audit, approval, working, episodic = mock_components

    assembler = MagicMock(spec=ContextAssembler)
    assembler.assemble.return_value = ContextBundle(
        contents=[{"source": "past-episode", "text": "relevant context", "tokens": 10, "truncated": False}],
        total_tokens=10,
        budget_tokens=4000,
    )

    loop = ExecutionLoop(
        registry=registry,
        runtime=runtime,
        environment=env,
        policy=policy,
        audit=audit,
        approval=approval,
        working_memory=working,
        episodic_memory=episodic,
        context_assembler=assembler,
    )

    task = Task(description="run tests", skill_id="shell.execute", input_params={"command": "pytest"})
    mission = Mission(goal_text="test the project", tasks=[task])

    await loop.execute_mission(mission)
    assert assembler.assemble.called


async def test_execution_loop_works_without_assembler(mock_components):
    """ExecutionLoop should work without a context_assembler (backward compatible)."""
    registry, runtime, env, policy, audit, approval, working, episodic = mock_components

    loop = ExecutionLoop(
        registry=registry,
        runtime=runtime,
        environment=env,
        policy=policy,
        audit=audit,
        approval=approval,
        working_memory=working,
        episodic_memory=episodic,
    )

    task = Task(description="run tests", skill_id="shell.execute", input_params={"command": "pytest"})
    mission = Mission(goal_text="test the project", tasks=[task])

    result = await loop.execute_mission(mission)
    assert result.status == MissionStatus.COMPLETED
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/core/test_loop_context.py -v`
Expected: FAIL — `ExecutionLoop` doesn't accept `context_assembler`.

**Step 3: Add context_assembler to ExecutionLoop**

In `src/atlas/core/loop.py`, add the import and modify the constructor:

Add to imports (line 5-6 area):

```python
from atlas.memory.retrieval import ContextAssembler
from atlas.contracts.types import ContextQuery
```

Update `__init__` (lines 55-77) to add `context_assembler` parameter:

```python
    def __init__(
        self,
        registry: SkillRegistry,
        runtime: InvocationRuntime,
        environment: EnvironmentFacade,
        policy: PolicyEngine,
        audit: AuditLogger,
        approval: ApprovalWorkflow,
        working_memory: WorkingMemoryStore,
        episodic_memory: EpisodicMemoryStore,
        forge=None,
        max_replans: int = 2,
        context_assembler: ContextAssembler | None = None,
    ):
        self._registry = registry
        self._runtime = runtime
        self._env = environment
        self._policy = policy
        self._audit = audit
        self._approval = approval
        self._working = working_memory
        self._episodic = episodic_memory
        self._forge = forge
        self._max_replans = max_replans
        self._context_assembler = context_assembler
```

In `execute_mission`, before the task execution loop (before line 87 `while i < len(mission.tasks):`), add context retrieval:

```python
        # Retrieve episodic context if assembler is available
        context_text = ""
        if self._context_assembler:
            try:
                recent_episodes = await self._episodic.query_recent(limit=50)
                query = ContextQuery(
                    purpose="planning",
                    task_description=mission.goal_text,
                    token_budget=4000,
                )
                bundle = self._context_assembler.assemble(query, recent_episodes)
                if bundle.contents:
                    context_text = "\n\n".join(c["text"] for c in bundle.contents)
                    logger.info("Assembled %d tokens of episodic context", bundle.total_tokens)
            except Exception as e:
                logger.warning("Context assembly failed, proceeding without: %s", e)
```

Also update the replan prompt to include the assembled context. Change line 114 from `context="",` to `context=context_text,`:

```python
                replan_prompt = build_replan_prompt(
                    original_goal=mission.goal_text,
                    failed_task_desc=task.description,
                    error=task.error or "unknown",
                    remaining_tasks=remaining_descs,
                    skills=skills_desc,
                    context=context_text,
                )
```

**Step 4: Run tests**

Run: `source .venv/bin/activate && pytest tests/unit/core/test_loop_context.py -v`
Expected: ALL PASS

**Step 5: Run all tests to verify no regressions**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: ALL PASS

**Step 6: Run linter**

Run: `source .venv/bin/activate && ruff check src/atlas/core/loop.py tests/unit/core/test_loop_context.py`
Expected: No errors

**Step 7: Commit**

```bash
git add src/atlas/core/loop.py tests/unit/core/test_loop_context.py
git commit -m "feat: wire ContextAssembler into ExecutionLoop for episodic context retrieval"
```

---

### Task 9: Wire everything in cli.py

**Files:**
- Modify: `src/atlas/cli.py:120-182`

**Step 1: Update cli.py to construct and pass vector search components**

In `src/atlas/cli.py`, add imports near the top:

```python
from atlas.memory.retrieval import ContextAssembler
```

In `_run_goal`, after `episodic = EpisodicMemoryStore(db)` (line 159), add:

```python
    # Initialize vector search components if enabled
    context_assembler = ContextAssembler()
    embedding_provider = None
    vector_store = None

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
            vector_store = VectorStore(db, model=config.memory.vector_search.model)

            # Update episodic store with embedding components
            episodic = EpisodicMemoryStore(
                db, embedding_provider=embedding_provider, vector_store=vector_store,
            )

            # Run migration if needed
            migration = VectorMigration(db, episodic, vector_store, embedding_provider)
            if not await migration.is_complete():
                click.echo("[vector-search] Migrating existing episodes...")
                count = await migration.run()
                if count:
                    click.echo(f"[vector-search] Embedded {count} episodes")

            click.echo("[vector-search] Semantic search enabled")
        except Exception as e:
            click.echo(f"[vector-search] Disabled: {e}", err=True)
```

Update the `ExecutionLoop` construction (line 172) to pass the assembler:

```python
    loop = ExecutionLoop(
        registry=registry,
        runtime=runtime,
        environment=env,
        policy=policy,
        audit=audit,
        approval=approval,
        working_memory=working,
        episodic_memory=episodic,
        forge=forge,
        context_assembler=context_assembler,
    )
```

**Step 2: Run all tests**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: ALL PASS

**Step 3: Run linter**

Run: `source .venv/bin/activate && ruff check src/atlas/cli.py`
Expected: No errors

**Step 4: Commit**

```bash
git add src/atlas/cli.py
git commit -m "feat: wire vector search components into CLI goal command"
```

---

### Task 10: Integration test — full pipeline

**Files:**
- Create: `tests/integration/test_vector_search.py`

**Step 1: Write the integration test**

Create `tests/integration/test_vector_search.py`:

```python
"""Integration test: record episode → embed → search semantically → correct episode surfaces."""

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from atlas.contracts.types import ContextQuery, Episode, EpisodeType
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
    db, episodic_no_vec, vector_store, provider = pipeline

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
```

**Step 2: Run integration tests**

Run: `source .venv/bin/activate && pytest tests/integration/test_vector_search.py -v`
Expected: ALL PASS

**Step 3: Run full test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: ALL PASS

**Step 4: Run linter**

Run: `source .venv/bin/activate && ruff check src/ tests/`
Expected: No errors

**Step 5: Commit**

```bash
git add tests/integration/test_vector_search.py
git commit -m "test: add vector search integration tests — full pipeline and degradation"
```

---

## Verification

After all tasks, run:

```bash
source .venv/bin/activate && pytest tests/ -v && ruff check src/ tests/
```

Expected: All tests pass, no lint errors. New test count should be approximately 237 (baseline) + ~25 new tests.
