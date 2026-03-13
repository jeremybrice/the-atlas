# Mission Brief

**Playbook:** feature-build
**Design Doc:** docs/plans/2026-03-13-atlas-phase2-design.md
**Implementation Plan:** docs/plans/2026-03-13-atlas-phase2-implementation.md
**Created:** 2026-03-13

## Requirements Summary

1. **Daemon architecture** — background process with PID file, Unix domain socket, JSON request/response protocol. CLI commands: `atlas daemon start/stop/status`. `atlas goal` forwards to daemon if running, else runs inline.
2. **Observation Engine** — filesystem watches via `watchdog` with debouncing and pattern matching. Scheduled triggers with interval-based firing. All triggers produce normalized `ObservationEvent` dataclass.
3. **Reactive Execution** — event router matches events against configured rules (event type, source pattern, cooldown). Priority task queue (not FIFO) with deduplication. Replanning on task failure with error context.
4. **Skill Forge** — custom skill loader from `~/.atlas/skills/*.py`. Forge pipeline: gap detection, Claude generates skill code, validate/register. All forged skills start at `risk_level="high"`.
5. **Memory Completion** — procedural memory store (SQLite). Pattern extraction from episodes. Purpose-aware context assembly with ranking strategies per purpose.
6. **Configuration** — structured config loading from YAML with defaults and user overrides. New sections: daemon, observation, reactive, skills.forge.

## Key Files

**Extend existing:**
- `src/atlas/contracts/types.py` — add ObservationEvent, Procedure, DaemonCommand, DaemonResponse, EventType
- `src/atlas/core/loop.py` — add replanning on failure, forge integration
- `src/atlas/core/tasks.py` — upgrade TaskQueue with priority and dedup
- `src/atlas/cli.py` — add daemon/watch commands, config loading, skill loader
- `src/atlas/memory/retrieval.py` — purpose-aware ranking and procedure support
- `config/default.yaml` — expand with Phase 2 settings
- `pyproject.toml` — add watchdog dependency

**Create new:**
- `src/atlas/daemon/` — protocol.py, manager.py, loop.py
- `src/atlas/observation/` — watcher.py, scheduler.py, router.py, engine.py
- `src/atlas/skills/loader.py`, `src/atlas/skills/forge.py`
- `src/atlas/memory/procedural.py`, `src/atlas/memory/patterns.py`
- `src/atlas/config.py`

## Test Command

```bash
pytest tests/ -v && ruff check src/ tests/
```

## Developer Callouts

- Python 3.12+ only — use `str | None` syntax, not `Optional`
- Absolute imports only: `from atlas.x import Y`, never relative across domains
- All errors must extend `RetriableError` or `FatalError` from `contracts/errors.py`
- `correlation_id` propagated via `ExecutionContext` through all cross-domain calls
- Claude bridge is the only mocked component — real SQLite with `tmp_path` fixtures
- Anthropic SDK switch is done — do not revert to CLI subprocess

## Success Criteria

1. `atlas daemon start` launches background process, `status` reports state, `stop` shuts down
2. Filesystem watcher detects changes and emits debounced ObservationEvents
3. Scheduled triggers fire at configured intervals
4. Event router matches events to rules with cooldown enforcement
5. Priority task queue orders by priority and deduplicates
6. Failed tasks trigger replanning with error context (up to 2 retries)
7. Custom skills load from `~/.atlas/skills/*.py` on startup
8. Skill Forge generates, validates, and registers new skills
9. Procedural memory stores/retrieves/updates procedures with success rates
10. Pattern extraction identifies repeated sequences and recurring failures
11. Context assembler uses purpose-aware ranking
12. Configuration loads from YAML with defaults and overrides
13. All existing 79 tests continue to pass
14. All new code has corresponding tests
15. `ruff check src/ tests/` passes
