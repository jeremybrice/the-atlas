# ATLAS — Autonomous Tool-Learning Agent System

ATLAS is an autonomous agent platform that decomposes goals into tasks, executes them using a learned skill set, and improves over time through episodic memory and trust-based autonomy escalation. It runs as a CLI tool or a background daemon with a real-time web dashboard.

Built on Claude as the reasoning backbone, ATLAS adds persistent memory, policy-governed execution, approval workflows, and a self-expanding skill library around it.

## How It Works

```
User Goal → Planning (Claude) → Task Queue → Execution Loop → Results
                                     ↑               ↓
                              Context Assembly   Episodic Memory
                              (FTS5 + Vector)    (learned outcomes)
```

1. You submit a goal in natural language
2. Claude decomposes it into a task plan (JSON or numbered list)
3. Each task maps to a skill (file.read, shell.execute, or a dynamically forged skill)
4. The policy engine checks permissions, the approval workflow gates risky actions
5. Results are recorded as episodes, feeding future context assembly
6. Trust accumulates per-skill — after 10 consecutive successes, autonomy escalates automatically

## Quick Start

```bash
# Prerequisites: Python 3.12+, an Anthropic API key
git clone https://github.com/jeremybrice/the-atlas.git
cd the-atlas

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

export ANTHROPIC_API_KEY="sk-ant-..."

# Run a goal
atlas goal "list all Python files in the current directory"

# Run tests
pytest tests/ -v
```

## CLI Commands

```bash
# Goal execution
atlas goal "your goal" --autonomy observe|suggest|act --auto-approve

# Background daemon
atlas daemon start|stop|status
atlas daemon pause|resume|kill <task_id>

# Approval rules (auto-approve/deny matching actions)
atlas rules list
atlas rules add --skill "file.*" --risk low --decision allow
atlas rules remove <rule_id>

# Trust management
atlas trust status
atlas trust recommendations
atlas trust accept|dismiss <recommendation_id>

# Credential vault (encrypted storage)
atlas vault set <service> <key>
atlas vault list
atlas vault delete <service> <key>

# Filesystem watches (daemon mode)
atlas watch add <pattern>
atlas watch list
```

## Web Dashboard

A real-time monitoring dashboard served by the daemon at `http://localhost:8484/`.

```bash
# Enable in config
cat > ~/.atlas/config/atlas.yaml << 'EOF'
webhook:
  enabled: true
  dashboard_enabled: true
EOF

atlas daemon start
open http://localhost:8484/
```

Single-file Alpine.js + Tailwind CSS frontend — no build step, no npm. Dark terminal command-center aesthetic with:

- **Status bar** — live daemon state, uptime, health indicators, goal input, emergency controls
- **Missions tab** — expandable mission list with task breakdown and status badges
- **Skills tab** — registered skills with risk level badges and tags
- **Trust tab** — per-skill trust records and pending autonomy recommendations
- **Rules tab** — standing approval rule management (add/remove)
- **Audit tab** — scrollable action history
- **Memory tab** — episode, mission, and embedding counts
- **Config tab** — current system configuration

Auto-polls every 3-5 seconds. All interactive controls (pause/resume, goal submit, trust accept/dismiss, rule management) work inline.

## Architecture

ATLAS is organized into 6 domains with strict contracts between them:

```
src/atlas/
├── contracts/        # Shared types, errors, interface ABCs
├── core/             # Execution loop, missions, task queue
├── memory/           # Episodic, working, procedural, vector, context assembly
├── skills/           # Registry, runtime, 4 seed skills, skill forge
├── env/              # Filesystem, process execution, Claude bridge
├── control/          # Policy engine, audit log, approval, trust, emergency
├── integrations/     # Dashboard, webhooks, vault, MCP bridge, GitHub connector
├── daemon/           # Background daemon with Unix socket + HTTP server
├── observation/      # Filesystem watcher, scheduler, event router
└── cli.py            # Click CLI entry point
```

### Core (src/atlas/core/)

The execution loop is the central plan-act-observe-reflect cycle:

- **ExecutionLoop** — sequentially executes a mission's tasks, checking permissions via the policy engine, requesting approval for risky actions, recording outcomes to episodic memory, and replanning up to 2 times on failure
- **Mission** — a user goal decomposed into an ordered task list by Claude
- **Task** — a single executable unit mapped to a skill, with input params, expected outcome, retry count, and priority
- **TaskQueue** — priority queue with deduplication support

Every cross-domain call propagates an `ExecutionContext` (correlation_id, mission_id, task_id) for end-to-end tracing.

### Memory (src/atlas/memory/)

Five memory subsystems feed context into planning and execution:

| Memory Type | Storage | Purpose |
|-------------|---------|---------|
| **Episodic** | SQLite + FTS5 | Records mission outcomes, searchable by full-text and vector similarity |
| **Working** | In-memory (OrderedDict) | Current operational context, LRU eviction at 100 keys |
| **Procedural** | SQLite | Learned workflows with trigger patterns and success rates |
| **Vector** | SQLite BLOBs + numpy | Voyage AI embeddings for semantic episode retrieval |
| **Context Assembly** | — | Token-budgeted context builder that merges keyword + semantic scores |

The **ContextAssembler** builds purpose-aware context bundles (planning, execution, reflection) within a configurable token budget (default 4000). When vector search is enabled, it combines FTS5 keyword scores with cosine similarity scores using configurable weights (default 0.6 semantic / 0.4 keyword).

### Skills (src/atlas/skills/)

Four seed skills ship with ATLAS:

| Skill | Risk | What it does |
|-------|------|-------------|
| `file.read` | Low | Read file contents |
| `file.write` | Medium | Write/create files |
| `file.search` | Low | Glob-based file search |
| `shell.execute` | High | Run shell commands with timeout |

The **Skill Forge** dynamically generates new skills when the agent encounters a capability gap. It prompts Claude to write a Python module, validates the output, and registers it to the skill registry. Custom skills persist to `~/.atlas/skills/`.

MCP tools are auto-registered as skills via the **MCPBridge** with a `mcp.` prefix.

### Control Plane (src/atlas/control/)

Every action flows through the control plane:

```
Proposed Action → PolicyEngine → AuditLogger → ApprovalWorkflow → Execute
                  (check risk)    (log it)      (gate if needed)
```

- **PolicyEngine** — evaluates actions against autonomy level (observe/suggest/act), risk level, blocked paths, and per-skill overrides
- **AuditLogger** — append-only SQLite log of every action with correlation_id tracing
- **ApprovalWorkflow** — interactive terminal approval with standing rule support. Type `always` or `never` at a prompt to create persistent rules
- **ApprovalRuleStore** — persistent rules with glob matching on skill patterns, risk levels, and path prefixes. Rules can have expiration dates
- **TrustTracker** — per-skill success/failure tracking. After 10 consecutive successes, recommends autonomy escalation. After 3 failures in a sliding window, recommends demotion. Users accept or dismiss recommendations via CLI or dashboard
- **EmergencyController** — asyncio.Event-based pause/resume and per-task kill. Checked before each task execution in the loop

### Environment (src/atlas/env/)

The environment facade routes actions to providers:

- **FilesystemProvider** — read, write, search, directory listing
- **ProcessProvider** — async subprocess execution with configurable timeout (default 30s)
- **ClaudeCodeBridge** — Anthropic SDK wrapper (claude-sonnet-4-20250514, 2048 max tokens). This is the only component mocked in tests

### Integrations (src/atlas/integrations/)

- **DashboardServer** — aiohttp REST API with 20+ endpoints for monitoring and control
- **Dashboard UI** — single-file Alpine.js + Tailwind frontend served at `GET /`
- **WebhookServer** — receives external events (GitHub pushes, etc.) with HMAC signature verification
- **CredentialVault** — encrypted credential storage using Fernet with PBKDF2 key derivation (SHA256, 480k iterations)
- **MCPBridge** — registers Model Context Protocol tools as ATLAS skills
- **GitHubConnector** — GitHub API integration with rate limiting (60 RPM)
- **EventBridge** — routes external events to the observation engine

### Daemon (src/atlas/daemon/)

The background daemon provides:

- **Unix socket server** — JSON-RPC protocol for CLI-to-daemon communication (goal, pause, resume, kill, status commands)
- **HTTP server** — aiohttp on port 8484 (configurable) serving the dashboard API and webhook endpoints
- **MCP server connections** — auto-discovers and registers MCP tools on startup

### Observation Engine (src/atlas/observation/)

Enables reactive, event-driven agent behavior:

- **FilesystemWatcher** — monitors directories for changes with configurable debounce (default 5s)
- **ScheduledTrigger** — periodic goal execution on a timer
- **EventRouter** — matches events to reactive rules using pattern matching, with per-rule cooldown

## Configuration

ATLAS loads `config/default.yaml` at startup, overridden by `~/.atlas/config/atlas.yaml`.

Key configuration sections:

```yaml
control:
  autonomy_level: act_within_bounds    # observe | suggest | act_within_bounds
  blocked_paths: ["~/.ssh", "~/.gnupg"]

trust:
  escalation_threshold: 10             # consecutive successes before escalation
  demotion_failure_count: 3            # failures in window before demotion

memory:
  vector_search:
    enabled: false                     # requires VOYAGE_API_KEY
    model: voyage-3-lite
    semantic_weight: 0.6

skills:
  forge_enabled: true                  # dynamic skill generation
  seed_skills: [file.read, file.write, file.search, shell.execute]

webhook:
  enabled: false
  dashboard_enabled: false
  port: 8484
```

See `config/default.yaml` for the full configuration reference.

## Database

All state lives in a single SQLite database at `~/.atlas/data/atlas.db` (WAL mode). Tables:

| Table | Purpose |
|-------|---------|
| `episodes` + `episodes_fts` | Episodic memory with FTS5 full-text search |
| `episode_embeddings` | Vector embeddings for semantic search |
| `missions` | Goal decompositions |
| `tasks` | Individual task records within missions |
| `audit_log` | Append-only action log |
| `trust_records` | Per-skill success/failure tracking |
| `trust_recommendations` | Pending autonomy escalation/demotion suggestions |
| `approval_rules` | Standing approval/denial rules |
| `credentials` | Encrypted credential vault |
| `procedures` | Learned workflows |
| `entity_mappings` | External service ID mappings |

Delete `~/.atlas/` to fully reset.

## REST API

When the daemon runs with `dashboard_enabled: true`, these endpoints are available at `http://localhost:8484`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Daemon state, uptime, active task |
| GET | `/api/health` | Subsystem health checks |
| GET | `/api/missions` | Recent missions (last 50) |
| GET | `/api/tasks` | Tasks, optionally filtered by `?mission_id=` |
| GET | `/api/skills` | Registered skills with risk levels |
| GET | `/api/memory/stats` | Episode, mission, and embedding counts |
| GET | `/api/audit` | Audit log entries (`?limit=50`) |
| GET | `/api/config` | Non-sensitive configuration |
| GET | `/api/connectors` | Configured external connectors |
| POST | `/api/goal` | Submit a goal (`{"goal_text": "..."}`) |
| POST | `/api/emergency/pause` | Pause the daemon |
| POST | `/api/emergency/resume` | Resume the daemon |
| POST | `/api/emergency/kill` | Kill a task (`{"task_id": "..."}`) |
| GET | `/api/approvals/rules` | List standing approval rules |
| POST | `/api/approvals/rules` | Add a rule |
| DELETE | `/api/approvals/rules/{id}` | Remove a rule |
| GET | `/api/trust/recommendations` | Pending trust recommendations (`?status=pending`) |
| POST | `/api/trust/recommendations/{id}/accept` | Accept a recommendation |
| POST | `/api/trust/recommendations/{id}/dismiss` | Dismiss a recommendation |
| GET | `/api/trust/records` | Per-skill trust records |

## Error Model

All errors extend one of two base classes that determine retry behavior:

- **RetriableError** — transient failures (network, rate limits, timeouts). Callers should backoff and retry
- **FatalError** — permanent failures (permission denied, skill not found, invalid credentials). Callers should abort or escalate

Specific errors: `ClaudeCodeError`, `ClaudeCodeUnavailableError`, `SkillInvocationError`, `SkillNotFoundError`, `PermissionDeniedError`, `MemoryStoreError`, `ConnectorError`, `CredentialError`, `ApprovalTimeoutError`, `ContextBudgetExceededError`.

## Testing

```bash
pytest tests/ -v          # all tests (318 passing)
pytest tests/unit/ -v     # unit tests only
pytest tests/integration/ # cross-domain integration tests
ruff check src/ tests/    # lint
ruff format --check .     # format check
```

Testing philosophy:

- **Real SQLite** in all tests via `tmp_path` fixtures — no database mocks
- **ClaudeCodeBridge is the only mock** — everything else runs against real implementations
- **Integration-focused** — most value is in cross-domain tests, not unit tests of thin wrappers
- **Unit test complex logic** — PolicyEngine, ContextAssembler, TaskQueue, Claude response parsing

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | Yes | Claude API access |
| `VOYAGE_API_KEY` | No | Vector search embeddings (Voyage AI) |

## Project Status

- **Phase 1 (MVP)** — Complete. CLI goal execution, 4 seed skills, policy engine, audit log, episodic memory.
- **Phase 2 (Full)** — Partial. Reactive mode, Skill Forge, dashboard API, GitHub integration.
- **Phase 3 (Advanced)** — In progress. Vector search, control plane completion (emergency, trust, approval rules), web dashboard.

## Tech Stack

- **Python 3.12+** — asyncio for I/O, synchronous for fast lookups
- **SQLite** — single database, WAL mode, FTS5 full-text search
- **Anthropic SDK** — Claude as reasoning backbone
- **aiohttp** — HTTP server for dashboard and webhooks
- **Alpine.js + Tailwind CSS** — dashboard frontend (CDN, no build step)
- **Voyage AI** — optional vector embeddings for semantic search
- **watchdog** — filesystem monitoring
- **cryptography** — Fernet encryption for credential vault

## License
