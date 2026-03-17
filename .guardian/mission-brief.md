# Mission Brief

**Playbook:** feature-build
**Design Doc:** docs/plans/2026-03-17-phase3-stage-d1-vector-search-design.md
**Implementation Plan:** docs/plans/2026-03-17-phase3-stage-d1-vector-search.md
**Created:** 2026-03-17

## Requirements Summary

1. **EmbeddingProvider** — Wraps Voyage AI API (`voyage-3-lite`), embed/embed_query/embed_batch methods, returns numpy arrays, graceful error handling (returns None on API failure)
2. **VectorStore** — SQLite BLOBs in `episode_embeddings` table, numpy cosine similarity search, store/store_batch/search/has_embedding/count methods
3. **Hybrid retrieval** — `ContextAssembler.merge_scores()` and `assemble_ranked()` combining FTS5 keyword (0.4 weight) + vector similarity (0.6 weight)
4. **FTS5 scoring** — `EpisodicMemoryStore.search_scored()` returning normalized relevance scores, add `lessons` to FTS5 index
5. **Embed on record** — `EpisodicMemoryStore.record()` embeds episodes when provider is available, never blocks episode recording on embedding failure
6. **Batch migration** — `VectorMigration` embeds all existing episodes on first run, tracks completion in `metadata` table
7. **ExecutionLoop wiring** — `ContextAssembler.assemble()` called before task planning, `ContextBundle` passed to Claude bridge via context_text
8. **CLI wiring** — Construct vector search components in `_run_goal` when `memory.vector_search.enabled` is true
9. **Graceful degradation** — Falls back to keyword-only search when Voyage API is unavailable

## Key Files

- `src/atlas/memory/embeddings.py` — NEW: EmbeddingProvider (Voyage AI wrapper)
- `src/atlas/memory/vector_store.py` — NEW: VectorStore (SQLite BLOB + cosine similarity)
- `src/atlas/memory/migration.py` — NEW: VectorMigration (batch embed existing episodes)
- `src/atlas/memory/retrieval.py` — MODIFY: Add merge_scores, assemble_ranked, refactor assemble into _assemble_episodes
- `src/atlas/memory/episodic.py` — MODIFY: Add search_scored, embed-on-record, optional embedding_provider/vector_store
- `src/atlas/memory/store.py` — MODIFY: Add episode_embeddings + metadata tables, update FTS5 trigger to include lessons
- `src/atlas/config.py` — MODIFY: Add VectorSearchConfig dataclass, nest in MemoryConfig, update _merge_into_dataclass for nested dataclasses
- `config/default.yaml` — MODIFY: Add vector_search section under memory
- `src/atlas/core/loop.py` — MODIFY: Add context_assembler parameter, retrieve context before task planning loop
- `src/atlas/cli.py` — MODIFY: Wire vector search components in _run_goal
- `pyproject.toml` — MODIFY: Add voyageai and numpy dependencies

## Test Command

`source .venv/bin/activate && pytest tests/ -v`

## Developer Callouts

Follow CLAUDE.md conventions:
- Python 3.12+ with `str | None` syntax
- `from __future__ import annotations` is used in existing memory files — maintain consistency
- src layout imports: `from atlas.x import Y`
- Errors extend `RetriableError` or `FatalError` from `contracts/errors.py`
- Mock only `ClaudeCodeBridge` and Voyage AI API client, use real SQLite with `tmp_path`
- `correlation_id` propagated via `ExecutionContext` through all cross-domain calls
- Existing `ContextAssembler` tests must not break — refactor shares logic via `_assemble_episodes`
- `_merge_into_dataclass` in config.py needs to handle nested dataclasses for `VectorSearchConfig`

## Success Criteria

- All implementation tasks complete and pass guardians
- `EmbeddingProvider` embeds text via Voyage AI (mocked in tests)
- `VectorStore` stores/searches embeddings via numpy cosine similarity
- Hybrid retrieval merges FTS5 + vector scores correctly
- Episodes are embedded on record when provider is available
- Migration batch-embeds existing episodes on first run
- `ExecutionLoop` retrieves episodic context before planning
- Graceful degradation to keyword-only when Voyage unavailable
- All tests pass (baseline 237 + ~25 new)
- Lint clean (`ruff check src/ tests/`)
