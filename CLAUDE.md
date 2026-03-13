# ATLAS (Autonomous Tool-Learning Agent System)

## Naming

- **Repository:** `clap`
- **Python package:** `atlas`
- **Project codename:** ATLAS

## Quick Reference

```bash
# Activate the virtual environment
source .venv/bin/activate

# Install in dev mode
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check src/ tests/

# Run the CLI
atlas goal "your goal here"
atlas status
```

## Architecture

ATLAS is a 6-domain autonomous agent platform built on Claude Code CLI:

1. **Agent Core** (`src/atlas/core/`) — orchestration, task queue, execution loop
2. **Memory System** (`src/atlas/memory/`) — working memory, episodic memory, context assembly
3. **Skill Engine** (`src/atlas/skills/`) — skill registry, invocation runtime, seed skills
4. **Environment Interface** (`src/atlas/env/`) — filesystem, process, Claude Code bridge
5. **Integration Layer** (`src/atlas/integrations/`) — external service connectors (Phase 2)
6. **Control Plane** (`src/atlas/control/`) — policy engine, audit log, approval workflow

Cross-domain contracts live in `src/atlas/contracts/` (types, errors, interface ABCs). The Foundation Spec (`.docs/plans/00_foundation_spec.md`) is the source of truth for all cross-domain interfaces.

## Project Structure

```
src/atlas/              # installable Python package
  contracts/            # shared types, errors, interface ABCs
  core/                 # Agent Core (tasks, missions, execution loop)
  memory/               # Memory System (working, episodic, context assembler)
  skills/               # Skill Engine (registry, runtime, seed skills)
  env/                  # Environment Interface (filesystem, process, claude bridge)
  integrations/         # Integration Layer (Phase 2)
  control/              # Control Plane (policy, audit, approval)
  cli.py                # Click CLI entry point
tests/
  unit/                 # mirrors src/atlas/ structure
  integration/          # cross-domain flow tests
config/
  default.yaml          # default configuration
.docs/plans/            # architecture docs (vision, specs, domain plans)
docs/plans/             # implementation plans
```

## Conventions

- **Python 3.12+** — uses `str | None` syntax, no `from __future__ import annotations` needed in new files
- **asyncio** for I/O-bound operations, synchronous for fast lookups
- **src layout** — always import as `from atlas.x import Y`, never relative imports across domains
- **Contracts are canonical** — domain implementations conform to `contracts/interfaces.py`, not the other way around
- **Error hierarchy** — all errors extend `RetriableError` or `FatalError` from `contracts/errors.py`; callers branch on this to decide retry vs. abort
- **correlation_id** — propagated via `ExecutionContext` through all cross-domain calls for tracing

## Testing

- **Integration-focused** — most value is in cross-domain tests, not unit tests of thin wrappers
- **Unit test complex logic only** — PolicyEngine, ContextAssembler, TaskQueue, Claude response parsing
- **Claude Code is mocked** at the `ClaudeCodeBridge` boundary — the only mock in the suite
- **Real SQLite** in tests — use `tmp_path` fixtures, no database mocks
- Test fixtures `tmp_data_dir` and `tmp_workspace` are in `tests/conftest.py`

## Phase Status

- **Phase 1 (MVP):** Complete — CLI goal execution, 4 seed skills, policy engine, audit log, episodic memory
- **Phase 2 (Full):** Not started — reactive mode, Skill Forge, integrations, dashboard API
- **Phase 3 (Advanced):** Not started — multi-agent, vector search, browser automation

## Key Documents

- `.docs/plans/00_foundation_spec.md` — canonical interfaces, error model, Phase 1 scope, testing strategy
- `.docs/plans/INDEX.md` — master index of all architecture docs
- `docs/plans/2026-03-13-atlas-phase1-mvp.md` — Phase 1 implementation plan
- `.guardian/completion-report.md` — Phase 1 build results
