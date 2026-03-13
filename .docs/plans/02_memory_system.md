# Domain 2: Memory System — Detailed Goals

## Primary Mission
Design the persistent knowledge layer that gives ATLAS continuity across sessions and enables learning over time. The Memory System stores everything the agent knows, has experienced, and has learned how to do. It provides intelligent retrieval so the Agent Core can access the right context at the right time without overwhelming Claude Code's context window.

## Goals

### G2.1: Four-Tier Memory Architecture
Design a memory system with four distinct tiers, each serving a different purpose:

- **Working Memory**: The agent's current context. What task is active, what has happened in the current session, what is the current plan. Volatile, lives in RAM, structured for fast access. Analogous to a human's "what I'm thinking about right now." Feeds directly into Claude Code prompts as context.

- **Episodic Memory**: A chronological log of everything the agent has done and observed. Each episode records: what triggered the action, what the agent planned, what it executed, what happened, and what it learned. Indexed by time, task, domain, and outcome. Used for reflection ("last time I tried X, it failed because Y") and pattern recognition.

- **Semantic Memory**: Structured knowledge the agent has accumulated. Facts about the user's environment, preferences, project structures, codebase patterns, tool configurations. Organized as a knowledge graph or structured documents. Updated when the agent learns something new. Used to ground planning in reality.

- **Procedural Memory**: Knowledge of how to do things. This is tightly coupled to the Skill Engine; procedural memory IS the skill registry plus learned execution patterns. When the agent learns that "skill X works better with parameter Y in context Z," that's procedural memory.

### G2.2: Context Window Management
Design the system that decides what memory content gets injected into each Claude Code CLI call. The context window is finite and precious. The memory system must: rank and select the most relevant memories for the current task, compress and summarize older memories to fit more context, track what context has already been provided in the current session (to avoid redundancy), and adapt retrieval strategy based on the type of reasoning being performed (planning needs different context than debugging).

### G2.3: Memory Persistence and Storage
Design the storage layer. Memory must survive daemon restarts, system reboots, and even migrations. Consider: SQLite for structured data (episodes, entities, relationships), JSON/Markdown files for human-readable knowledge documents, vector embeddings for semantic search (optional, but architecturally plan for it), and a clear backup/export strategy. Inherit and evolve forge-lib's existing SQLite + JSON schema approach.

### G2.4: Memory Lifecycle Management
Design how memories are created, updated, consolidated, and eventually archived or forgotten. Not all memories are equally valuable. The system must handle: automatic memory creation from agent actions and observations, periodic consolidation (compressing many similar episodes into general patterns), relevance decay (older, less-accessed memories become less prominent), and explicit user corrections ("that's wrong, actually X is true").

### G2.5: Retrieval Interface
Design the API that other domains use to query memory. This must support: direct lookup (get episode #1234), semantic search (find memories relevant to "deploying Python apps"), temporal queries (what did I do yesterday), filtered queries (all episodes where skill X was used), and composite queries (most relevant context for planning task Y given current working memory Z). The retrieval interface is the most performance-critical component; it's called on nearly every reasoning step.

### G2.6: Learning and Pattern Extraction
Design how the memory system identifies patterns across episodes and extracts reusable knowledge. When the agent has completed a task type multiple times, the memory system should recognize the pattern and create a generalized procedure or heuristic. This feeds into both semantic memory (new knowledge) and procedural memory (improved skills). This is the foundation of the "self-improving" capability.

## Cross-Domain Dependencies
- **Agent Core**: Primary consumer of memory. Writes episodes, reads context for planning.
- **Skill Engine**: Procedural memory is shared with skill registry. Skill execution history informs skill improvement.
- **Environment Interface**: Environment observations are a primary source of new memories.
- **Integration Layer**: External entity state (Jira ticket status, Slack channel context) persists in semantic memory.
- **Control Plane**: Memory access patterns are auditable. Sensitive memories may have access restrictions.

## Key Constraints
- Must not require external services (no cloud vector DBs); everything runs locally
- Must handle graceful migration from existing forge-lib data structures
- Context window management must be token-aware (know approximate token counts)
- Must support the user inspecting and correcting memories (transparency requirement)
- Storage footprint must be reasonable for a desktop application (not unbounded growth)
