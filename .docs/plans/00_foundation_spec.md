# ATLAS Foundation Spec

## Purpose

This document sits between PROJECT_VISION.md (vision and domain descriptions) and the six domain plans (internal architecture per domain). It owns everything that crosses domain boundaries or is shared infrastructure: canonical interfaces, package structure, Phase 1 scope, error model, testing strategy, deployment, and observability.

**Where domain plans define interface contracts that differ from this document, this document wins.** Domain plans remain authoritative for their internal architecture.

## Naming

- **Repository**: `clap`
- **Python package**: `atlas`
- **Project codename**: ATLAS (Autonomous Tool-Learning Agent System)

## Forge Migration: Clean Break

The existing Forge ecosystem (7 plugins, forge-lib, 15 JSON schemas, 124 tests) serves as inspiration for seed skill design. ATLAS does not maintain backward compatibility with Forge data structures, databases, or plugin interfaces. This is a clean break, not a migration.

---

## 1. Document Hierarchy

```
PROJECT_VISION.md          — Vision, operating modes, domain descriptions
    │
    ▼
00_foundation_spec.md      — THIS DOCUMENT
    │                        Package structure, canonical interfaces,
    │                        Phase 1 scope, error model, testing,
    │                        deployment, observability
    │
    ▼
01-06 Domain Plans          — Internal architecture per domain
```

---

## 2. Python Package Structure

```
clap/                          ← repo root (git)
├── .docs/plans/               ← architecture docs
├── src/
│   └── atlas/                 ← installable Python package
│       ├── __init__.py
│       ├── __main__.py        ← `python -m atlas` entry point
│       ├── cli.py             ← Click/Typer CLI: `atlas goal`, `atlas status`, etc.
│       ├── core/              ← Domain 1: Agent Core
│       │   ├── __init__.py
│       │   ├── events.py      ← AtlasEvent, EventIngress, EventClassifier
│       │   ├── missions.py    ← Mission, MissionPlanner
│       │   ├── tasks.py       ← Task, TaskGraph, TaskQueueManager
│       │   └── loop.py        ← ExecutionLoop
│       ├── memory/            ← Domain 2: Memory System
│       │   ├── __init__.py
│       │   ├── working.py     ← WorkingMemoryStore
│       │   ├── episodic.py    ← EpisodicMemoryStore
│       │   ├── semantic.py    ← SemanticMemoryStore
│       │   ├── retrieval.py   ← UnifiedRetrievalLayer, ContextAssembler
│       │   └── store.py       ← SQLite connection, schema, migrations
│       ├── skills/            ← Domain 3: Skill Engine
│       │   ├── __init__.py
│       │   ├── registry.py    ← SkillRegistry
│       │   ├── runtime.py     ← InvocationRuntime
│       │   └── models.py      ← SkillDefinition, SkillResult, SkillDescriptor
│       ├── env/               ← Domain 4: Environment Interface
│       │   ├── __init__.py
│       │   ├── facade.py      ← EnvironmentFacade
│       │   ├── filesystem.py  ← FilesystemProvider
│       │   ├── process.py     ← ProcessProvider
│       │   ├── claude.py      ← ClaudeCodeBridge
│       │   └── state.py       ← EnvironmentStateModel
│       ├── integrations/      ← Domain 5: Integration Layer
│       │   ├── __init__.py
│       │   ├── manager.py     ← IntegrationManager
│       │   ├── connector.py   ← Connector ABC
│       │   ├── vault.py       ← CredentialVault
│       │   └── connectors/    ← one file per connector
│       ├── control/           ← Domain 6: Control Plane
│       │   ├── __init__.py
│       │   ├── policy.py      ← PolicyEngine
│       │   ├── audit.py       ← AuditLogger
│       │   ├── approval.py    ← ApprovalWorkflowEngine
│       │   ├── emergency.py   ← EmergencyControlSystem
│       │   └── config.py      ← ConfigurationManager
│       └── contracts/         ← Shared types and interfaces
│           ├── __init__.py
│           ├── types.py       ← shared data models (UUIDs, enums, base classes)
│           ├── interfaces.py  ← ABCs defining all cross-domain interfaces
│           └── errors.py      ← unified error hierarchy
├── tests/
│   ├── unit/                  ← mirrors src/atlas/ structure
│   ├── integration/           ← cross-domain tests
│   └── conftest.py
├── config/
│   └── default.yaml           ← default ATLAS configuration
├── pyproject.toml             ← project metadata, dependencies, build config
└── .gitignore
```

Key decisions:

- **`src/` layout** — prevents accidental imports of the uninstalled package. Modern Python packaging standard.
- **`atlas/contracts/`** — single home for all cross-domain interfaces, types, and errors. Domain plans reference these, not each other.
- **`atlas/cli.py`** — CLI-first interaction for Phase 1. No daemon yet.
- **Repo is `clap`, package is `atlas`** — documented explicitly.

---

## 3. Canonical Cross-Domain Interfaces

All six domain plans defer to these signatures. Implemented as Python ABCs in `atlas/contracts/interfaces.py`.

### Concurrency Model

**asyncio** is the concurrency model for ATLAS. I/O-bound operations (skill invocation, environment actions, Claude Code calls, approvals) are `async`. Fast lookups (permission checks, state queries, capability search) are synchronous.

### Memory System Interface

Consumed by Core, Skills, Control.

```python
class MemoryInterface(ABC):
    # Context retrieval (synchronous — Core blocks while assembling)
    def retrieve_context(self, query: ContextQuery) -> ContextBundle: ...
    def get_working_context(self) -> WorkingContext: ...

    # Episode recording (asynchronous — fire and forget)
    def record_episode(self, episode: Episode) -> EpisodeId: ...

    # Working memory
    def set_working(self, key: str, value: Any, ttl: int | None = None) -> None: ...
    def get_working(self, key: str) -> Any | None: ...
    def clear_working(self) -> None: ...

    # Episodic queries
    def query_episodes(self, filter: EpisodeFilter, limit: int = 50) -> list[Episode]: ...
    def search_episodes(self, text_query: str, limit: int = 20) -> list[Episode]: ...

    # Semantic knowledge
    def store_knowledge(self, entry: KnowledgeEntry) -> EntryId: ...
    def query_knowledge(self, topic: str, limit: int = 10) -> list[KnowledgeEntry]: ...

    # Stats (for Control Plane dashboard)
    def get_stats(self) -> MemoryStats: ...
```

### Skill Engine Interface

Consumed by Core.

```python
class SkillEngineInterface(ABC):
    # Discovery (synchronous)
    def search(self, query: CapabilityQuery) -> list[SkillDescriptor]: ...
    def get(self, skill_id: str) -> SkillDefinition: ...
    def list_all(self, filter: SkillFilter | None = None) -> list[SkillDescriptor]: ...

    # Execution (async)
    async def invoke(self, skill_id: str, params: dict,
                     context: InvocationContext) -> SkillResult: ...

    # Registration
    def register(self, skill: SkillDefinition) -> str: ...
    def unregister(self, skill_id: str) -> None: ...
```

### Environment Interface

Consumed by Core, Skills.

```python
class EnvironmentInterface(ABC):
    # Action execution (async)
    async def execute(self, action: EnvironmentAction) -> ActionResult: ...

    # State queries (synchronous, fast)
    def get_state(self) -> EnvironmentState: ...
    def get_capabilities(self) -> list[Capability]: ...

    # Claude Code bridge
    async def claude_oneshot(self, prompt: str,
                             system_prompt: str | None = None) -> ClaudeResponse: ...
```

### Control Plane Interface

Consumed by all domains.

```python
class ControlPlaneInterface(ABC):
    # Permission check (synchronous, sub-millisecond)
    def check_permission(self, action: ProposedAction) -> PolicyDecision: ...
    def get_autonomy_level(self, domain: str,
                           skill: str | None = None) -> AutonomyLevel: ...

    # Audit logging (async, never blocks)
    def log_action(self, entry: AuditEntry) -> None: ...

    # Approval workflow (blocks until response or timeout)
    async def request_approval(self, request: ApprovalRequest) -> ApprovalResult: ...
```

### Integration Layer Interface

Consumed by Skills, Core.

```python
class IntegrationInterface(ABC):
    async def execute(self, request: IntegrationRequest) -> IntegrationResult: ...
    def list_connectors(self) -> list[ConnectorInfo]: ...
    def health_check(self) -> dict[str, HealthStatus]: ...
```

---

## 4. Unified Error Model

Lives in `atlas/contracts/errors.py`.

### Error Hierarchy

```python
class AtlasError(Exception):
    """Base for all ATLAS errors. Carries a correlation_id for tracing."""
    def __init__(self, message: str, correlation_id: str | None = None,
                 cause: Exception | None = None): ...

# --- Retriable vs. Fatal ---
class RetriableError(AtlasError):
    """Caller should retry (with backoff). Includes max_retries hint."""
    def __init__(self, message: str, max_retries: int = 3, **kwargs): ...

class FatalError(AtlasError):
    """Do not retry. Escalate or abort."""

# --- Domain-specific families ---

# Control Plane
class PermissionDeniedError(FatalError): ...
class ApprovalTimeoutError(RetriableError): ...

# Environment
class EnvironmentActionError(RetriableError): ...
class ClaudeCodeError(RetriableError): ...
class ClaudeCodeUnavailableError(FatalError): ...

# Skills
class SkillNotFoundError(FatalError): ...
class SkillInvocationError(RetriableError): ...
class SkillValidationError(FatalError): ...

# Memory
class MemoryStoreError(RetriableError): ...
class ContextBudgetExceededError(FatalError): ...

# Integration
class ConnectorError(RetriableError): ...
class CredentialError(FatalError): ...
```

### Design Decisions

- **Two base branches: `RetriableError` and `FatalError`** — every caller knows immediately whether to retry or escalate. The Execution Loop uses this to decide: retry the task, replan, or fail the mission.
- **`correlation_id` on every error** — a UUID that traces an action from Core through Skills through Environment through Control Plane. Set once when the Execution Loop starts a task step, propagated through every call.
- **`cause` chaining** — when a `SkillInvocationError` wraps an `EnvironmentActionError` wraps a `ClaudeCodeError`, the full chain is preserved for debugging and audit logging.

---

## 5. Phase 1 MVP Scope

### Demo Scenario

A user runs `atlas goal "refactor the logging in src/utils.py to use structured logging"` from the terminal. ATLAS:

1. Takes the goal, queries Claude Code (one-shot) with available skill descriptions and environment state
2. Gets back a linear task plan (3-5 steps)
3. Executes each step sequentially — reading files, reasoning about changes, writing files
4. Checks Control Plane permission before each action
5. Logs every action to the audit log
6. Records the episode to episodic memory
7. Reports the outcome to the terminal

No daemon. No reactive mode. No parallel tasks. No self-authoring. No integrations. One run, one goal, start to finish.

### Per-Domain Boundaries

| Domain | In Scope | Out of Scope |
|---|---|---|
| **Core** | CLI entry point, linear task decomposition (no DAG), sequential execution loop, basic reflection (success/failure) | Reactive mode, task graphs, parallel execution, preemption, mission recovery |
| **Memory** | Working memory (dict), episodic memory (SQLite + FTS5), basic context assembly with token counting | Semantic memory, procedural memory, Pattern Extractor, purpose-aware ranking |
| **Skills** | Registry with manual registration, invocation runtime for Python functions and CLI commands, 4 seed skills | Skill Forge, Workflow Composer, Skill Evolver, capability search beyond keyword matching |
| **Environment** | Filesystem provider (read/write/list/search), process provider (execute command), Claude Code bridge (one-shot only), environment state snapshot | Observation Engine, session mode, Network/Desktop providers, sandboxing |
| **Integration** | None | All connectors, Credential Vault, Event Bridge, Entity Mapper, MCP Bridge |
| **Control** | Policy engine with 3 autonomy levels (observe/suggest/act-within-bounds), audit logger (SQLite, no hash chain), terminal approval prompts, emergency pause via SIGINT | Trust escalation, batch/standing approvals, Dashboard API, config hot-reload |

### Seed Skills

```python
"file.read"        # read file contents, returns string
"file.write"       # write content to file path
"file.search"      # glob/regex search in directory tree
"shell.execute"    # run a shell command, return stdout/stderr/exit code
```

### Interaction Model

Phase 1 runs as a single CLI invocation that blocks until the goal is complete or fails. No background daemon, no socket, no HTTP server.

```
$ atlas goal "add error handling to the API routes in src/api/"
[planning] Decomposing goal into tasks...
[task 1/4] Reading src/api/routes.py
[task 2/4] Analyzing error handling patterns...
[approval] Write to src/api/routes.py? (y/n/details)
[task 3/4] Writing updated routes.py
[task 4/4] Verifying changes compile
[complete] 4/4 tasks succeeded. Episode recorded.
```

The daemon model comes in Phase 2 when reactive mode requires a long-running process.

---

## 6. Testing Strategy

### Approach: Integration-Focused With Targeted Unit Tests

ATLAS is an orchestration system. The value is in how domains compose, not in individual components. Unit-testing thin wrappers (FilesystemProvider, WorkingMemoryStore) adds cost without catching real bugs. Integration tests that exercise cross-domain flows with real SQLite databases and mocked Claude Code responses are where bugs actually live.

### Testing Pyramid

```
         ╱  ╲
        ╱ E2E ╲          1-2 tests: full CLI invocation, goal → result
       ╱────────╲
      ╱Integration╲      ~20 tests: cross-domain flows
     ╱──────────────╲
    ╱   Unit (targeted)  ╲   ~40 tests: complex logic only
   ╱──────────────────────╲
```

### What Gets Unit Tested

- `PolicyEngine.evaluate()` — rule matching, priority ordering, boundary checks
- `ContextAssembler.assemble()` — token budgeting, ranking, truncation
- `TaskQueueManager` — dependency resolution, ordering, state transitions
- Claude Code response parsing — extracting structured task plans from LLM output
- Error classification — retriable vs. fatal decisions

### What Doesn't Get Unit Tested

- `FilesystemProvider` (wraps `pathlib`)
- `ProcessProvider` (wraps `subprocess`)
- `WorkingMemoryStore` (wraps `dict`)
- `AuditLogger` (wraps SQLite inserts)

These are covered by integration tests that exercise real flows.

### Claude Code Mocking

The `ClaudeCodeBridge` is mocked at the bridge boundary — the only mock in the test suite. Returns canned responses for known prompt patterns. Everything else uses real implementations with temp databases and temp directories.

### Test Runner

`pytest` with `pytest-asyncio`. No special framework.

---

## 7. Deployment & Packaging

### Installation

```bash
pip install -e ".[dev]"    # development install from repo
```

`pyproject.toml` defines:
- **Runtime deps**: `click` (CLI), `aiosqlite` (async SQLite), `pyyaml` (config)
- **Dev deps**: `pytest`, `pytest-asyncio`, `ruff` (linting/formatting)
- **Entry point**: `atlas` CLI command

```toml
[project.scripts]
atlas = "atlas.cli:main"
```

### Runtime Requirements

- Python 3.12+
- Claude Code CLI installed and authenticated (`claude` on PATH)
- No Docker, no cloud services, no external databases

### Data Directory

```
~/.atlas/
├── config/
│   └── atlas.yaml          ← user configuration
├── data/
│   └── atlas.db            ← single SQLite database
├── logs/
│   └── atlas.log           ← structured JSON log file
└── skills/
    └── seed/               ← built-in skill implementations
```

Key decisions:
- **Single SQLite database** — simpler backup, simpler transactions. Tables are logically separated.
- **`~/.atlas/` not project-local** — ATLAS is a desktop agent, not a per-project tool. Memory and skills persist across projects.
- **Structured JSON log** — separate from audit log. For operational debugging. Uses Python `logging` with JSON formatter.

### No Daemon in Phase 1

Phase 1 is a CLI that runs to completion. When Phase 2 introduces reactive mode, daemon infrastructure gets added then — likely `atlas daemon start` with PID file + Unix socket.

---

## 8. Observability

### Correlation IDs

When the Execution Loop picks up a task step, it generates a `correlation_id` (UUID). This ID propagates through every cross-domain call:

```
ExecutionLoop starts task step
  → correlation_id = "abc-123"
  → ControlPlane.check_permission(action, correlation_id="abc-123")
  → SkillEngine.invoke(skill_id, params, correlation_id="abc-123")
    → Environment.execute(action, correlation_id="abc-123")
      → ClaudeCodeBridge.oneshot(prompt, correlation_id="abc-123")
  → Memory.record_episode(episode, correlation_id="abc-123")
  → ControlPlane.log_action(entry, correlation_id="abc-123")
```

### ExecutionContext

```python
@dataclass
class ExecutionContext:
    correlation_id: str
    mission_id: str | None = None
    task_id: str | None = None
```

Every cross-domain interface method accepts an optional `ctx: ExecutionContext` parameter. The Execution Loop creates it; all downstream calls propagate it.

### Phase 1 Scope

- Correlation IDs on all cross-domain calls
- JSON structured log with correlation IDs
- Audit log entries carry correlation IDs
- Observability tools: `grep` and `sqlite3`
