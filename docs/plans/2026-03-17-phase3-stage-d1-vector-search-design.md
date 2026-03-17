# Phase 3 Stage D1: Vector Search — Design

**Date:** 2026-03-17
**Status:** Approved
**Depends on:** Phase 3 Stage B (complete)

## Overview

Vector Search adds semantic retrieval to ATLAS's episodic memory. Currently, episode search is keyword-only (SQLite FTS5) and the ContextAssembler exists but is not wired into the execution loop. This stage adds cloud-based embeddings via Voyage AI, hybrid keyword+semantic scoring, and wires context retrieval into the execution loop so past episodes inform planning.

## Key Decisions

- **Embedding provider:** Voyage AI (`voyage-3-lite`) — Anthropic's recommended embedding partner, consistent with ATLAS's cloud-model architecture
- **Vector storage:** numpy float32 BLOBs in SQLite, cosine similarity computed in Python — episode volumes (hundreds to low thousands) don't justify a SQLite extension
- **Retrieval strategy:** Hybrid scoring combining FTS5 keyword search and vector similarity (`0.6 * semantic + 0.4 * keyword`)
- **Migration:** Batch-embed all existing episodes on first run with Vector Search enabled
- **Execution loop wiring:** ContextAssembler called before task planning, ContextBundle passed to Claude bridge

## Architecture

### New Components

**EmbeddingProvider** (`src/atlas/memory/embeddings.py`)
- Wraps the Voyage AI API
- Methods: `embed(text) -> ndarray`, `embed_batch(texts) -> list[ndarray]`
- Single model: `voyage-3-lite`
- API key retrieved from CredentialVault (`voyage/api_key`)

**VectorStore** (`src/atlas/memory/vector_store.py`)
- Stores embeddings as BLOBs in `episode_embeddings` SQLite table
- Retrieves all embeddings, computes cosine similarity via numpy
- Methods: `store(episode_id, embedding)`, `store_batch(ids, embeddings)`, `search(query_embedding, limit) -> list[(episode_id, score)]`

### Modified Components

**ContextAssembler** (`src/atlas/memory/retrieval.py`)
- New hybrid retrieval: queries both FTS5 and VectorStore
- Merges results with weighted scoring
- Falls back to keyword-only if Voyage is unavailable

**ExecutionLoop** (`src/atlas/core/loop.py`)
- Calls `ContextAssembler.assemble()` before planning each task
- Passes `ContextBundle` to Claude Code bridge as additional context
- `context_assembler` added as optional constructor parameter

**EpisodicMemoryStore** (`src/atlas/memory/episodic.py`)
- After recording an episode, embeds and stores the vector
- Embedding failure does not block episode recording

**DatabaseStore** (`src/atlas/memory/store.py`)
- New `episode_embeddings` table
- New `metadata` table for migration tracking
- FTS5 trigger updated to include `lessons` field

## Data Flow

### Write Path

```
ExecutionLoop.execute_mission()
  → EpisodicMemoryStore.record(episode)
    → INSERT into episodes table + FTS5 index (existing)
    → EmbeddingProvider.embed(trigger_text + plan + outcome + lessons)
    → VectorStore.store(episode_id, embedding)
      → INSERT into episode_embeddings table
```

### Read Path

```
ExecutionLoop (before planning)
  → ContextAssembler.assemble(query)
    → FTS5 keyword search → scored keyword results
    → EmbeddingProvider.embed(query text)
    → VectorStore.search(query_embedding, limit) → scored semantic results
    → Merge & re-rank: 0.6 * semantic + 0.4 * keyword
    → Token-budgeted assembly (existing)
  → ContextBundle passed to Claude via bridge
```

### Migration

```
CLI or daemon startup (first run with vector search enabled)
  → EpisodicMemoryStore.query_recent(limit=ALL)
  → EmbeddingProvider.embed_batch(episode texts)
  → VectorStore.store_batch(episode_ids, embeddings)
  → metadata table: vector_migration_complete = timestamp
```

## Storage Schema

### New Tables

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

- `embedding` — numpy float32 array serialized via `ndarray.tobytes()`
- `model` — tracks which model produced the embedding for re-embedding detection
- `dimensions` — vector length for validation on load

### FTS5 Update

Add `lessons` to the FTS5 trigger so keyword search covers the same fields as the embedding text:

```sql
CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
    INSERT INTO episodes_fts(episode_id, trigger_text, plan, outcome, lessons)
    VALUES (new.episode_id, new.trigger_text, new.plan, new.outcome, new.lessons);
END;
```

## Hybrid Scoring

1. FTS5 keyword search returns up to N episodes with keyword relevance (SQLite `rank`, normalized to 0–1)
2. VectorStore returns up to N episodes with cosine similarity scores (0–1)
3. Union by `episode_id`
4. Both sets: `final_score = 0.6 * semantic + 0.4 * keyword`
5. One set only: available score scaled by its weight
6. Sort by `final_score` descending, pass to token-budgeted assembly

## Configuration

```yaml
memory:
  vector_search:
    enabled: false          # opt-in, requires Voyage API key in vault
    model: "voyage-3-lite"
    semantic_weight: 0.6
    keyword_weight: 0.4
    search_limit: 50
```

Voyage API key stored in CredentialVault: `atlas vault set voyage api_key <key>`

`enabled` defaults to `false` — no surprise API calls.

## Error Handling

- **Voyage API failure on write:** Log warning, store episode without embedding. Missing embeddings picked up by migration on next startup.
- **Voyage API failure on read:** Fall back to keyword-only search. Log warning.
- **Corrupt or missing embedding BLOB:** Skip in vector results, log error. Keyword search still works.
- **API key not configured:** Vector search disabled entirely, keyword-only mode. Info log on startup.

## Dependencies

| Package | Purpose |
|---------|---------|
| `voyageai` | Voyage AI embedding API client |
| `numpy` | Vector storage serialization and cosine similarity |

## Testing Strategy

### Unit Tests

- **EmbeddingProvider** — mock Voyage API client. Single embed, batch embed, error handling (timeout, rate limit), text composition from episode fields.
- **VectorStore** — real SQLite (`tmp_path`). Store/retrieve round-trip, cosine similarity ranking, store_batch, missing embeddings.
- **Hybrid scoring** — merge logic. Episodes in both sets, keyword-only, semantic-only, score normalization, weight configuration.

### Integration Tests

- **Full pipeline** — record episode → embed → search semantically → correct episode surfaces. Real SQLite, mocked Voyage API.
- **Graceful degradation** — Voyage unavailable → keyword-only fallback returns results, logs warning.
- **Migration** — insert episodes without embeddings → run migration → all episodes embedded.
- **Context assembly wiring** — mock ClaudeCodeBridge, verify ContextBundle reaches bridge call.

### Not Tested

- Actual Voyage API calls (requires real API key and network)
- Embedding quality/relevance (Voyage's responsibility)
