# ATLAS Phase 2 Design: Daemon + Reactive Loop + Learning

**Date:** 2026-03-13
**Status:** Approved
**Scope:** Daemon architecture, Observation Engine, Reactive Execution, Skill Forge, Memory Completion

## Motivation

Phase 1 built a working agent that plans and executes goals via CLI. But everything it does — read files, write files, run commands, plan tasks — Claude Code already does better interactively. Phase 2 focuses exclusively on capabilities Claude Code *cannot* do natively:

1. **Run autonomously in the background** without an active terminal session
2. **React to external events** (file changes, schedules) without human prompting
3. **Learn and improve over time** via persistent memory and self-authored skills
4. **Compose workflows** that run unattended

## Architectural Change: Anthropic SDK

Phase 1 used `claude -p` (Claude Code CLI) for LLM calls. This was fragile — subprocess management, undocumented output formats, timeout issues. Phase 2 uses the Anthropic Python SDK directly:

- **Claude API (via SDK):** Reasoning, planning, code generation
- **ATLAS Skills:** Execution (file ops, shell, future integrations)

This is cleaner: ATLAS owns execution through its skill engine, Claude handles reasoning.

## 1. Daemon Architecture

ATLAS becomes a long-running background process.

### CLI Commands

```
atlas daemon start     # start background daemon
atlas daemon stop      # graceful shutdown
atlas daemon status    # running? uptime, recent activity
atlas goal "..."       # submit to daemon, or run inline if no daemon
atlas watch add "pat"  # add filesystem watch trigger
atlas watch list       # list active triggers
```

### Implementation

- Single asyncio event loop in a background process
- PID file: `~/.atlas/daemon.pid`
- Unix domain socket: `~/.atlas/atlas.sock` (JSON request/response protocol)
- Signal handling: SIGTERM → graceful shutdown, SIGHUP → config reload
- `atlas goal` detects running daemon and forwards; falls back to inline if no daemon

### Why Unix Socket

Simpler than HTTP, no port conflicts, no auth needed, same-machine only (local-first).

## 2. Observation Engine

The daemon passively monitors the environment and generates events.

### Three Trigger Types

**Filesystem watches** — `watchdog` library (cross-platform FSEvents/inotify):
- Watch patterns: `src/**/*.py`, `tests/`, `.github/workflows/`
- Events: created, modified, deleted
- Debouncing: configurable cooldown per pattern (default 5s)

**Scheduled triggers** — cron-like syntax:
- `every 30m: check for stale branches`
- `daily at 09:00: summarize yesterday's git activity`
- Simple interval or cron expression

**Goal triggers** — user-submitted goals via CLI or socket.

### Event Normalization

All triggers produce an `ObservationEvent`:

```python
@dataclass
class ObservationEvent:
    event_id: str
    event_type: str          # "filesystem", "scheduled", "goal"
    source: str              # "watch:src/**/*.py", "schedule:branch-cleanup", "cli"
    payload: dict            # type-specific data
    timestamp: datetime
    priority: int = 5        # 1 (highest) to 10 (lowest)
```

## 3. Reactive Execution

Events flow: **Observe -> Classify -> Plan -> Execute -> Reflect**.

### Event Router

Matches events against registered rules. Rules map event patterns to goal templates:

```yaml
reactive:
  rules:
    - name: "test-on-change"
      trigger:
        type: filesystem
        pattern: "src/**/*.py"
      goal: "Run pytest for changed files: {changed_files}"
      cooldown: 60s
      autonomy: act
    - name: "lint-on-save"
      trigger:
        type: filesystem
        pattern: "src/**/*.py"
      goal: "Run ruff check on {changed_files}"
      cooldown: 10s
      autonomy: act
```

### Task Queue Upgrade

- Priority queue (not FIFO) — reactive tasks can preempt
- Concurrent execution limit (default: 1, configurable)
- Task deduplication (same goal within cooldown window is dropped)

### Replanning on Failure

- If a task fails, Claude replans with error context (up to 2 retries)
- If replan also fails, record failure episode and move on

## 4. Skill Forge

When the agent hits a capability gap, it creates a new skill.

### Gap Detection

1. Planning: Claude proposes a task with no matching skill
2. Execution: skill invocation fails suggesting missing capability
3. Either triggers `SkillForge.request(gap_description, context)`

### Forge Pipeline

1. **Analyze** — examine gap, search episodic memory for similar attempts
2. **Specify** — generate skill_id, name, description, input/output schema, risk_level
3. **Implement** — generate handler code (async Python function)
4. **Test** — generate test cases, run in subprocess sandbox
5. **Register** — if tests pass, register. If not, retry once with error context
6. **Record** — episode: what gap, what was created, outcome

### Skill Storage

Generated skills saved to `~/.atlas/skills/` as Python modules, loaded on daemon start:

```python
# ~/.atlas/skills/github_pr_create.py
SKILL_ID = "github.pr.create"
SKILL_NAME = "Create GitHub PR"
SKILL_DESCRIPTION = "Creates a pull request on GitHub using gh CLI"
SKILL_RISK = "high"

async def handler(params: dict) -> dict:
    # generated implementation
    ...
```

All forged skills start at `risk_level="high"` requiring approval.

## 5. Memory Completion

### Procedural Memory (New Tier)

Stores learned workflows:

```python
@dataclass
class Procedure:
    procedure_id: str
    name: str               # "run-tests-after-change"
    description: str
    trigger_pattern: str    # when to suggest this procedure
    steps: list[dict]       # ordered skill invocations
    success_rate: float     # tracked over time
    last_used: datetime
    created_from: str       # episode_id that spawned this
```

SQLite table, same database. Procedures are suggested during planning.

### Pattern Extraction (Background Task)

Runs every N minutes (default 30):
- Repeated skill sequences for similar goals -> create Procedure
- Repeated errors -> create avoidance rule
- Consistently failing skills -> flag for Forge improvement

### Purpose-Aware Context Assembly

Upgrade existing assembler with ranking strategies:
- **Planning:** recent similar goals, available skills, procedures
- **Execution:** current mission state, working memory
- **Reflection:** recent failures, lessons learned
- **Forge:** past skill creation attempts, similar skills

## 6. Configuration

```yaml
atlas:
  data_dir: "~/.atlas"
  log_level: "INFO"

daemon:
  socket_path: "~/.atlas/atlas.sock"
  pid_file: "~/.atlas/daemon.pid"
  max_concurrent_tasks: 1

control:
  autonomy_level: "act_within_bounds"
  allowed_read_paths: ["."]
  allowed_write_paths: ["."]
  blocked_paths: ["~/.ssh", "~/.gnupg"]

memory:
  working_memory_max_keys: 100
  episode_retention_days: 90
  context_default_token_budget: 4000
  pattern_extraction_interval_minutes: 30

skills:
  seed_skills: ["file.read", "file.write", "file.search", "shell.execute"]
  forge_enabled: true
  forge_max_retries: 1
  custom_skills_dir: "~/.atlas/skills"

environment:
  command_timeout_seconds: 30

observation:
  filesystem_debounce_seconds: 5
  watches: []

reactive:
  enabled: false          # opt-in, not default
  rules: []
  cooldown_default_seconds: 60
```

## 7. New Dependencies

```
watchdog>=4.0      # filesystem monitoring (cross-platform)
```

One new dependency. The Anthropic SDK was added in Phase 1 fixes.

## 8. Deferred to Phase 3

- Integration Layer (Jira, Slack, GitHub connectors, Credential Vault)
- MCP Bridge (expose/consume MCP tools)
- Dashboard API / Tauri UI
- Multi-agent coordination
- Vector embedding semantic search
- Browser automation
- Trust escalation (auto-adjusting autonomy)
- Webhook ingestion endpoint
