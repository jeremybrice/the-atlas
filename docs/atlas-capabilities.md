# ATLAS — What It Can Do

## Quick Start

```bash
# Set your API key
export ANTHROPIC_API_KEY="sk-ant-..."

# Run a goal directly
atlas goal "create a hello world script"

# Start the background daemon
atlas daemon start

# Submit goals to the daemon
atlas goal "run pytest and fix any failures"

# Check daemon status
atlas daemon status

# Stop the daemon
atlas daemon stop
```

## Goal Execution

Give ATLAS a goal in plain English. It decomposes it into tasks, picks the right skills, and executes them.

```bash
atlas goal "add a GitHub Actions CI workflow that runs pytest and ruff on every push"
atlas goal "refactor the config module to use dataclasses instead of raw dicts"
atlas goal "find all TODO comments in the codebase and list them"
```

ATLAS reads your project files (pyproject.toml, directory structure) to produce accurate output. Medium/high risk actions (writing files, running shell commands) require your approval.

## Background Daemon

The daemon runs in the background and accepts goals without an active terminal session.

```bash
atlas daemon start    # launches background process
atlas daemon status   # shows PID, uptime
atlas daemon stop     # graceful shutdown
```

When the daemon is running, `atlas goal` automatically forwards to it via Unix socket instead of running inline.

## Filesystem Watching

The daemon can watch for file changes and react automatically. Watches are configured in `~/.atlas/config/atlas.yaml`:

```yaml
observation:
  watches:
    - "/path/to/your/project/src"

reactive:
  enabled: true
  rules:
    - name: "test-on-change"
      trigger:
        type: filesystem
        pattern: "*.py"
      goal: "Run pytest for changed files: {path}"
      cooldown: 60
```

## Scheduled Triggers

Configure recurring tasks in the daemon:

```yaml
reactive:
  rules:
    - name: "daily-lint"
      trigger:
        type: scheduled
        interval: 3600
      goal: "Run ruff check on the entire codebase"
```

## Skill Forge

When ATLAS encounters a task it doesn't have a skill for, it can create one automatically. Claude generates the skill code, ATLAS validates and registers it. All forged skills start requiring approval (high risk).

Custom skills are stored in `~/.atlas/skills/` as Python files and loaded on startup.

## Built-in Skills

| Skill | What it does | Risk |
|-------|-------------|------|
| `file.read` | Read file contents | Low |
| `file.write` | Write/create files | Medium |
| `file.search` | Glob/pattern search | Low |
| `shell.execute` | Run shell commands | High |

## Replanning

If a task fails during execution, ATLAS asks Claude to replan the remaining work using the error context. Up to 2 replan attempts before giving up.

## Memory

ATLAS remembers what it's done:
- **Episodic memory** — records every mission (goal, plan, actions, outcome)
- **Procedural memory** — stores learned workflows with success rates
- **Pattern extraction** — discovers repeated patterns from past episodes
- **Working memory** — transient state during execution

## Configuration

Default config is in `config/default.yaml`. Override with `~/.atlas/config/atlas.yaml`:

```yaml
# Key settings
daemon:
  max_concurrent_tasks: 1

control:
  autonomy_level: "act_within_bounds"  # observe, suggest, or act_within_bounds

skills:
  forge_enabled: true
  custom_skills_dir: "~/.atlas/skills"

memory:
  pattern_extraction_interval_minutes: 30
```

## Autonomy Levels

| Level | Behavior |
|-------|----------|
| `observe` | Plans but doesn't execute — shows you what it would do |
| `suggest` | Executes but asks approval for every action |
| `act_within_bounds` | Auto-approves low risk, asks for medium/high, blocks critical |

```bash
atlas goal "do something" --autonomy observe
atlas goal "do something" --autonomy suggest
atlas goal "do something" --autonomy act    # default
```
