# Domain 2: Memory System — Architectural Design Plan

## 1. Architecture Overview

The Memory System is ATLAS's knowledge backbone. It stores everything the agent has learned, experienced, and knows how to do, and it provides intelligent retrieval so the Agent Core gets the right context for each reasoning step without overflowing Claude Code's context window.

The architecture follows a **tiered storage model** with a unified retrieval layer on top. Each memory tier has different characteristics (volatility, structure, access patterns) but all are queryable through a single interface. A **Context Assembler** sits between the retrieval layer and consumers, responsible for selecting, ranking, compressing, and assembling memory content into context bundles that fit within token budgets.

```
                    ┌──────────────────────────────┐
                    │       Context Assembler       │
                    │  (token budgeting, ranking,   │
                    │   compression, assembly)      │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │     Unified Retrieval Layer   │
                    │  (query routing, relevance    │
                    │   scoring, result merging)    │
                    └──────────────┬───────────────┘
                                   │
          ┌────────────┬───────────┼───────────┬────────────┐
          │            │           │           │            │
   ┌──────▼─────┐ ┌───▼────┐ ┌───▼────┐ ┌────▼─────┐ ┌───▼──────┐
   │  Working   │ │Episodic│ │Semantic│ │Procedural│ │ Pattern  │
   │  Memory    │ │ Memory │ │ Memory │ │  Memory  │ │ Extractor│
   │ (RAM)      │ │(SQLite)│ │(SQLite │ │ (SQLite+ │ │ (async)  │
   │            │ │        │ │ +JSON) │ │  JSON)   │ │          │
   └────────────┘ └────────┘ └────────┘ └──────────┘ └──────────┘
```

## 2. Component Breakdown

### 2.1 Working Memory Store
**Responsibility**: Maintains the agent's current operational context in RAM for fast access.

Contains: the active mission and task state, recent conversation turns with Claude Code, current environment observations, and the assembled context from the last reasoning step. Working memory is volatile; it is reconstructed from persistent stores on daemon restart.

**Public Interface**:
- `set(key: str, value: Any, ttl: int = None) -> None`
- `get(key: str) -> Any | None`
- `get_current_context() -> WorkingContext`
- `clear_session() -> None`

**Internal structure**: A keyed store (Python dict) with optional TTL expiration. Capped at a configurable maximum size (e.g., 50K tokens worth of content) with LRU eviction.

### 2.2 Episodic Memory Store
**Responsibility**: Chronological record of everything the agent has done and observed.

Each episode is a structured record of: what triggered the action, the plan formed, the actions taken, the outcomes observed, and any lessons extracted. Episodes are the raw material for pattern extraction and reflection.

**Public Interface**:
- `record(episode: Episode) -> EpisodeId`
- `query(filter: EpisodeFilter, limit: int) -> list[Episode]`
- `get_by_id(episode_id: EpisodeId) -> Episode`
- `get_timeline(start: datetime, end: datetime) -> list[Episode]`
- `search(text_query: str, limit: int) -> list[Episode]`

**Storage**: SQLite table with full-text search index on episode descriptions and outcomes.

### 2.3 Semantic Memory Store
**Responsibility**: Structured knowledge the agent has accumulated about its world.

Organized as **knowledge entries** — facts, relationships, and observations about entities in the agent's environment: user preferences, project structures, codebase patterns, tool configurations, external service states. Each entry has a topic, content, confidence level, and provenance (where the knowledge came from).

**Public Interface**:
- `store(entry: KnowledgeEntry) -> EntryId`
- `update(entry_id: EntryId, content: str, source: str) -> None`
- `query(topic: str, limit: int) -> list[KnowledgeEntry]`
- `get_by_topic(topic: str) -> list[KnowledgeEntry]`
- `invalidate(entry_id: EntryId, reason: str) -> None`

**Storage**: SQLite table with topic indexing. Large knowledge documents (e.g., learned codebase maps) stored as JSON files with SQLite metadata pointers.

### 2.4 Procedural Memory Store
**Responsibility**: Knowledge of how to do things, tightly coupled with the Skill Engine.

Stores: skill execution patterns (parameters that work well in certain contexts), learned workflows (common skill chains), heuristics (rules of thumb derived from experience), and failure avoidance patterns (things that don't work). Procedural memory is the bridge between the Memory System and the Skill Engine; the Skill Engine's registry IS procedural memory.

**Public Interface**:
- `store_procedure(proc: Procedure) -> ProcedureId`
- `find_procedures(task_description: str) -> list[Procedure]`
- `record_execution(proc_id: ProcedureId, outcome: ExecutionOutcome) -> None`
- `get_best_approach(task_type: str) -> Procedure | None`

**Storage**: SQLite with JSON-serialized procedure definitions.

### 2.5 Pattern Extractor
**Responsibility**: Asynchronous background process that analyzes episodic memory to identify patterns and generate new semantic/procedural knowledge.

Runs periodically (configurable interval) or on-demand after significant episodes. Looks for: repeated task types (opportunity to generalize into a procedure), recurring failures (opportunity to create avoidance rules), frequently accessed knowledge (candidate for working memory pre-loading), and stale knowledge (entries not accessed in a long time, candidate for archival).

**Public Interface**:
- `run_extraction() -> ExtractionReport`
- `schedule(interval: timedelta) -> None`
- `extract_from_episodes(episode_ids: list[EpisodeId]) -> list[ExtractedPattern]`

### 2.6 Context Assembler
**Responsibility**: Builds token-budgeted context bundles for Claude Code prompts.

This is the most critical component for practical performance. Every Claude Code call needs context, but the context window is finite. The Context Assembler: receives a query describing what kind of reasoning is about to happen, retrieves candidate content from all memory tiers via the Retrieval Layer, scores candidates by relevance to the current task, compresses older/less-relevant content (summarization), assembles a context bundle that fits within the specified token budget, and tracks what was included (so subsequent calls don't repeat the same context unnecessarily).

**Public Interface**:
- `assemble(query: ContextQuery) -> ContextBundle`
- `estimate_tokens(content: str) -> int`
- `get_assembly_history() -> list[AssemblyRecord]`

**Dependencies**: All memory stores (via Retrieval Layer), token counting utility.

### 2.7 Unified Retrieval Layer
**Responsibility**: Routes queries to appropriate memory stores and merges results.

Provides a single query interface that can search across all tiers. Handles: query routing (determine which stores are relevant), parallel retrieval from multiple stores, result merging and deduplication, and relevance scoring across heterogeneous result types.

**Public Interface**:
- `retrieve(query: RetrievalQuery) -> RetrievalResult`
- `retrieve_context(query: str, max_tokens: int) -> ContextBundle` (convenience method that chains through Context Assembler)

## 3. Data Models

### Episode
- `episode_id`: UUID
- `timestamp`: datetime
- `episode_type`: enum (task_execution, observation, reflection, skill_creation, user_interaction)
- `trigger`: string (what caused this episode)
- `plan`: string (what the agent intended)
- `actions`: list[ActionRecord] (what was actually done)
- `outcome`: string (what happened)
- `lessons`: list[string] (extracted takeaways)
- `mission_id`: UUID | None
- `task_id`: UUID | None
- `tags`: list[string]
- Storage: SQLite with FTS5 index.

### KnowledgeEntry
- `entry_id`: UUID
- `topic`: string (hierarchical, e.g., "user.preferences.coding_style")
- `content`: string
- `confidence`: float (0.0 to 1.0)
- `source`: string (which episode or user input created this)
- `created_at`, `updated_at`: datetime
- `access_count`: int
- `last_accessed`: datetime
- Storage: SQLite.

### Procedure
- `procedure_id`: UUID
- `name`: string
- `description`: string
- `task_type`: string (what kind of task this procedure handles)
- `steps`: list[ProcedureStep]
- `success_rate`: float
- `execution_count`: int
- `context_requirements`: list[string] (what context must be true for this to apply)
- `linked_skill_ids`: list[string]
- Storage: SQLite + JSON.

### ContextBundle
- `bundle_id`: UUID
- `query`: ContextQuery
- `contents`: list[ContextItem] (ranked, with source attribution)
- `total_tokens`: int
- `budget_tokens`: int
- `assembled_at`: datetime
- Storage: In-memory (ephemeral).

### ContextQuery
- `purpose`: enum (planning, execution, reflection, skill_authoring)
- `task_description`: string
- `mission_context`: string | None
- `token_budget`: int
- `recency_weight`: float (how much to favor recent memories)
- `relevance_threshold`: float

## 4. Interface Contracts

### Memory System → Agent Core (consumed by Core)
```python
# Primary retrieval interface
memory.retrieve_context(query: ContextQuery) -> ContextBundle
memory.get_working_context() -> WorkingContext

# Episode recording
memory.record_episode(episode: Episode) -> EpisodeId

# Working memory management
memory.update_working_memory(key: str, value: Any) -> None
memory.clear_working_memory() -> None
```
All retrieval calls are **synchronous** (Core blocks while assembling context). Episode recording is **asynchronous** (fire-and-forget, persisted in background).

### Memory System → Skill Engine
```python
# Procedural memory access (Skill Engine is primary consumer)
memory.get_procedures(task_type: str) -> list[Procedure]
memory.record_skill_execution(skill_id: str, outcome: ExecutionOutcome) -> None
memory.get_skill_history(skill_id: str) -> list[Episode]
```

### Memory System → Control Plane
```python
# Audit access
memory.get_episodes(filter: EpisodeFilter) -> list[Episode]
memory.get_memory_stats() -> MemoryStats

# User correction interface
memory.correct_knowledge(entry_id: EntryId, correction: str, source: str) -> None
```

## 5. State Management

**Episode Lifecycle**: Episodes are immutable once recorded. They can be tagged, linked, and archived but never modified. Archival moves episodes from the active SQLite table to an archive table, reducing query overhead.

**Knowledge Entry Lifecycle**: `active → stale → archived`. Entries become stale after a configurable period without access. Stale entries are deprioritized in retrieval. Archived entries are queryable but excluded from default context assembly. User corrections create a new entry and mark the old one as `superseded`.

**Recovery**: On restart, working memory is empty and rebuilt from: the most recent active mission state (from Agent Core's SQLite), the last N episodic memories, and relevant semantic knowledge entries. This "cold start" context assembly is a specific mode of the Context Assembler.

## 6. Design Patterns

- **Repository Pattern**: Each memory tier is a repository with a standard CRUD+ search interface.
- **Strategy Pattern**: Context Assembler uses pluggable ranking strategies depending on the query purpose (planning vs. reflection vs. skill authoring need different relevance criteria).
- **Observer Pattern**: Memory System emits events when significant new knowledge is created, allowing the Pattern Extractor and other consumers to react.
- **Decorator Pattern**: Memory entries can be wrapped with metadata (access counts, relevance scores) without modifying the core data.
- **CQRS (Command Query Responsibility Segregation)**: Writes (episode recording, knowledge updates) are separated from reads (context retrieval) with different optimization strategies for each.

## 7. Phased Rollout

**Phase 1 (MVP)**: Working memory as simple key-value store. Episodic memory with SQLite + FTS5 (text search, no embeddings). Basic semantic memory (flat topic-keyed entries). Context Assembler with simple token counting and recency-based ranking. No procedural memory yet (skills are stateless). No Pattern Extractor.

**Phase 2 (Full)**: Procedural memory integrated with Skill Engine. Pattern Extractor running on schedule. Context Assembler with purpose-aware ranking strategies. Knowledge entry lifecycle management (staleness, archival). Memory statistics and inspection API for Control Plane dashboard.

**Phase 3 (Advanced)**: Vector embedding-based semantic search (local embeddings, no cloud dependency). Cross-episode causal reasoning (episode A led to outcome B which informed decision C). Memory consolidation (compressing many similar episodes into generalized knowledge). Predictive context pre-loading (anticipate what context will be needed for likely next tasks).

## 8. Key Tradeoffs

**SQLite FTS5 vs. vector embeddings for search**: Phase 1 uses FTS5 (keyword-based full-text search). It's built into SQLite, zero external dependencies, and good enough for early use. Vector search is architecturally planned for Phase 3 but not required initially. This avoids premature complexity while keeping the door open.

**Single SQLite database vs. per-tier databases**: Chose single database with separate tables. Simpler backup, simpler transactions, simpler deployment. The tiers are logical, not physical. If performance demands it later, splitting is straightforward.

**Eager vs. lazy context assembly**: Chose lazy (assemble on demand). Eager pre-assembly would be faster at query time but wasteful (most assembled contexts are never used). The latency of on-demand assembly (single-digit milliseconds for SQLite queries + token counting) is acceptable.

**Mutable vs. immutable episodes**: Chose immutable. Episodes are historical records; modifying them undermines trust and auditability. Lessons can be extracted and stored separately as knowledge entries that CAN be updated.

## 9. Open Questions

- What is the right token estimation approach? Character-based approximation (fast, inaccurate) vs. actual tokenizer (accurate, slower, requires tokenizer dependency)?
- How aggressive should archival be? Too aggressive and the agent forgets useful context; too conservative and search gets slow.
- Should the Pattern Extractor use Claude Code for pattern identification, or should it use rule-based heuristics? LLM-based extraction is powerful but expensive (each extraction cycle costs a Claude Code call).
- How should conflicting knowledge entries be resolved? If episodic memory contradicts semantic memory, which wins?
- What is the right granularity for episodic memory? One episode per task? Per action? Per mission? Granularity affects both storage volume and retrieval quality.
