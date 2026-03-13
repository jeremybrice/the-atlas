# Mission Brief

**Playbook:** feature-build
**Design Doc:** docs/plans/2026-03-13-atlas-phase1-mvp.md
**Created:** 2026-03-13

## Requirements Summary

1. **Shared contracts layer** — types.py (enums, data models, ExecutionContext), errors.py (RetriableError/FatalError hierarchy with correlation_id and cause chaining), interfaces.py (ABCs for MemoryInterface, SkillEngineInterface, EnvironmentInterface, ControlPlaneInterface)
2. **Control Plane** — PolicyEngine evaluating ProposedAction against 3 autonomy levels (observe/suggest/act-within-bounds) with path blocking; AuditLogger as append-only SQLite; ApprovalWorkflow with terminal prompts and auto-approve/deny modes for testing
3. **Memory System** — WorkingMemoryStore (LRU dict with max_keys eviction); EpisodicMemoryStore (SQLite with FTS5 full-text search for episodes); ContextAssembler (assembles episodes into token-budgeted ContextBundles prioritizing recency)
4. **Environment Interface** — FilesystemProvider (read/write/list/search via pathlib); ProcessProvider (async subprocess with timeout); ClaudeCodeBridge (one-shot `claude -p` with JSON response parsing); EnvironmentFacade routing EnvironmentAction to providers; EnvironmentStateModel for workspace snapshots
5. **Skill Engine** — SkillDefinition/SkillDescriptor models; SkillRegistry with keyword search; InvocationRuntime executing async handlers; 4 seed skills (file.read, file.write, file.search, shell.execute)
6. **Agent Core** — Task model with status lifecycle; TaskQueue (FIFO); MissionPlanner parsing Claude JSON or numbered-list responses into Task lists; ExecutionLoop running permission check → approval → skill invoke → audit log → episode record
7. **CLI** — `atlas goal "..."` Click command wiring all components, calling Claude for planning, executing the loop, reporting results; `atlas status` placeholder

## Key Files

```
src/atlas/contracts/types.py      — shared enums, data models, ExecutionContext
src/atlas/contracts/errors.py     — RetriableError/FatalError hierarchy
src/atlas/contracts/interfaces.py — cross-domain ABCs (source of truth)
src/atlas/control/policy.py       — PolicyEngine (autonomy levels, path blocking)
src/atlas/control/audit.py        — AuditLogger (append-only SQLite)
src/atlas/control/approval.py     — ApprovalWorkflow (terminal + auto modes)
src/atlas/memory/store.py         — SQLite schema and connection management
src/atlas/memory/working.py       — WorkingMemoryStore (LRU dict)
src/atlas/memory/episodic.py      — EpisodicMemoryStore (SQLite + FTS5)
src/atlas/memory/retrieval.py     — ContextAssembler (token budgeting)
src/atlas/env/filesystem.py       — FilesystemProvider
src/atlas/env/process.py          — ProcessProvider (async subprocess)
src/atlas/env/claude.py           — ClaudeCodeBridge (one-shot + response parsing)
src/atlas/env/facade.py           — EnvironmentFacade (routes actions to providers)
src/atlas/env/state.py            — EnvironmentStateModel
src/atlas/skills/models.py        — SkillDefinition, SkillHandler type
src/atlas/skills/registry.py      — SkillRegistry (keyword search)
src/atlas/skills/runtime.py       — InvocationRuntime
src/atlas/skills/seed.py          — 4 seed skill handlers
src/atlas/core/tasks.py           — Task model, TaskQueue
src/atlas/core/missions.py        — Mission, MissionPlanner, parse_task_plan
src/atlas/core/loop.py            — ExecutionLoop
src/atlas/cli.py                  — Click CLI (atlas goal, atlas status)
```

## Test Command

```
pytest tests/ -v
```

## Developer Callouts

None.

## Success Criteria

1. `pip install -e ".[dev]"` succeeds and `atlas` CLI is on PATH
2. `atlas --help` shows `goal` and `status` commands
3. `atlas goal "..."` calls Claude Code one-shot, parses the plan, executes tasks sequentially via seed skills, checks permissions, logs audit entries, records episodes
4. All unit tests pass: PolicyEngine, ContextAssembler, TaskQueue, Claude response parsing, error hierarchy
5. Integration test passes: ExecutionLoop wires Core + Skills + Environment + Control + Memory with real SQLite and temp files
6. E2E test passes: full goal execution with mocked Claude response, verifying file modification, episode recording, and audit entries
7. `pytest tests/ -v` — full suite green
