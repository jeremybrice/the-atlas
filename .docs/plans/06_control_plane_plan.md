# Domain 6: Control Plane — Architectural Design Plan

## 1. Architecture Overview

The Control Plane is ATLAS's governance and safety layer. Every action in the system passes through it for permission evaluation, and every outcome is recorded by it for audit. It is the first component initialized and the last shut down. It cannot be bypassed, and it cannot be overridden by the agent's own reasoning.

The architecture centers on a **Policy Engine** that evaluates every proposed action against a configurable set of rules. Surrounding it are an **Audit Logger** (append-only record of everything), an **Approval Workflow Engine** (human-in-the-loop gates), a **Dashboard API** (status exposure for frontends), and an **Emergency Control System** (immediate human intervention capabilities).

```
                    ┌──────────────────────────────┐
                    │       Policy Engine           │
                    │  (rules, autonomy levels,     │
                    │   boundary enforcement)       │
                    └──────────────┬───────────────┘
                                   │
       ┌───────────┬───────────────┼───────────────┬───────────┐
       │           │               │               │           │
  ┌────▼─────┐ ┌───▼────────┐ ┌───▼──────┐ ┌──────▼────┐ ┌───▼──────┐
  │  Audit   │ │  Approval  │ │Dashboard │ │ Emergency │ │  Config  │
  │  Logger  │ │  Workflow   │ │  API     │ │  Controls │ │  Manager │
  │          │ │  Engine     │ │          │ │           │ │          │
  └──────────┘ └────────────┘ └──────────┘ └───────────┘ └──────────┘

                    ┌──────────────────────────────┐
                    │     Trust Escalation          │
                    │     Tracker                   │
                    │  (success rates, autonomy     │
                    │   recommendations)            │
                    └──────────────────────────────┘
```

## 2. Component Breakdown

### 2.1 Policy Engine
**Responsibility**: Evaluates every proposed action against the configured rule set and returns a permission decision.

The engine is the hot path; every action in ATLAS passes through it, so it must be fast (sub-millisecond for typical evaluations). It evaluates: the global autonomy level, domain-specific autonomy overrides, skill-specific risk levels, resource boundaries (filesystem paths, network hosts), temporal rules (operating hours), and rate limits (actions per time window).

Rules are loaded from configuration and cached in memory. Rule evaluation is pure logic with no I/O.

**Public Interface**:
- `evaluate(action: ProposedAction) -> PolicyDecision`
- `get_autonomy_level(domain: str, skill: str) -> AutonomyLevel`
- `reload_rules() -> None`

**PolicyDecision** is one of: `allow` (proceed), `deny` (blocked, with reason), `require_approval` (pause for human), or `allow_with_logging` (proceed but flag for review).

### 2.2 Audit Logger
**Responsibility**: Append-only, tamper-resistant record of every significant event in ATLAS.

Every action, decision, observation, skill invocation, approval, error, and configuration change is logged. Entries include: timestamp, actor (which domain/component), action type, full action details, policy decision applied, outcome, and any side effects.

The audit log is separate from episodic memory. Memory is for the agent's learning; the audit log is for the user's oversight. They may contain overlapping data but serve different purposes and have different integrity requirements.

**Public Interface**:
- `log(entry: AuditEntry) -> None` (async, never blocks callers)
- `query(filter: AuditFilter) -> list[AuditEntry]`
- `get_recent(n: int) -> list[AuditEntry]`
- `export(start: datetime, end: datetime, format: str) -> ExportResult`

**Storage**: Append-only SQLite table with write-ahead logging. Entries are hashed in sequence (each entry includes hash of previous entry) to detect tampering. Log rotation by date with configurable retention.

### 2.3 Approval Workflow Engine
**Responsibility**: Manages human-in-the-loop approval when the Policy Engine requires it.

When an action requires approval: the engine creates an `ApprovalRequest` with full context (what, why, expected outcome, risks), notifies the user through available channels (terminal prompt, desktop notification, future Tauri UI), waits for response with configurable timeout, and returns the decision to the requesting domain.

Supports: individual approval (one action at a time), batch approval ("approve all filesystem writes for this mission"), standing approval ("always allow this skill in this context" — which creates a new policy rule), and delegation (auto-approve if a similar action was approved recently and the context matches).

**Public Interface**:
- `request_approval(request: ApprovalRequest) -> ApprovalResult`
- `list_pending() -> list[ApprovalRequest]`
- `approve(request_id: RequestId, scope: ApprovalScope) -> None`
- `deny(request_id: RequestId, reason: str) -> None`
- `set_timeout_policy(policy: TimeoutPolicy) -> None`

### 2.4 Dashboard API
**Responsibility**: Exposes system status for consumption by frontends (future Tauri UI, CLI status commands, monitoring tools).

Provides read-only access to: current agent state (idle, planning, executing, waiting for approval), active mission and task queue, recent audit log entries, pending approval requests, system health (all domains), skill registry summary, memory statistics, connector health, and configuration summary.

Implemented as a local HTTP server (bound to localhost only) with JSON responses. Alternatively, Unix socket for tighter security.

**Public Interface** (HTTP endpoints):
- `GET /status` — overall system state
- `GET /missions` — active and recent missions
- `GET /tasks` — task queue snapshot
- `GET /approvals` — pending approval requests
- `POST /approvals/:id/approve` — approve a request
- `POST /approvals/:id/deny` — deny a request
- `GET /audit` — recent audit entries with filtering
- `GET /health` — per-domain health checks
- `GET /skills` — skill registry summary
- `GET /memory/stats` — memory tier statistics
- `POST /emergency/pause` — pause all operations
- `POST /emergency/resume` — resume operations
- `POST /emergency/kill/:task_id` — kill a specific task

### 2.5 Emergency Control System
**Responsibility**: Provides immediate, unconditional human intervention capabilities.

Emergency controls bypass the normal approval workflow; they are direct commands that take effect immediately. Capabilities: **pause** (freeze all execution; in-flight actions complete but no new ones start), **resume** (unpause), **kill task** (abort a specific task immediately), **kill all** (abort all tasks, return to idle), **revoke skill** (immediately disable a specific skill), **rollback** (revert recent filesystem changes using side-effect logs from Audit Logger), and **shutdown** (clean daemon shutdown, checkpointing all state).

Emergency controls are accessible via: Unix signals (SIGINT for pause, SIGTERM for shutdown), CLI commands (`atlas emergency pause`), Dashboard API endpoints, and future Tauri UI buttons.

**Critical constraint**: Emergency controls must work even if other components are hanging or crashed. The implementation uses a dedicated thread/process that monitors control channels independently of the main execution loop.

**Public Interface**:
- `pause() -> None`
- `resume() -> None`
- `kill_task(task_id: str) -> None`
- `kill_all() -> None`
- `revoke_skill(skill_id: str) -> None`
- `rollback(n_actions: int) -> RollbackResult`
- `shutdown(graceful: bool) -> None`

### 2.6 Configuration Manager
**Responsibility**: Manages all ATLAS configuration with validation, versioning, and hot-reloading.

Configuration is stored as YAML files organized by domain: `core.yaml`, `memory.yaml`, `skills.yaml`, `environment.yaml`, `integrations.yaml`, `control.yaml`. The Config Manager: validates all config against JSON schemas on load, tracks configuration versions (every change creates a new version), supports hot-reloading (config changes take effect without restart where possible), provides a unified query interface (any component can read any config section), and fails safe (invalid config causes revert to last known good).

**Public Interface**:
- `get(section: str, key: str, default: Any) -> Any`
- `get_section(section: str) -> dict`
- `update(section: str, key: str, value: Any) -> None`
- `reload() -> ReloadResult`
- `get_version() -> ConfigVersion`
- `rollback_config(version: int) -> None`
- `validate() -> ValidationResult`

### 2.7 Trust Escalation Tracker
**Responsibility**: Tracks the agent's performance to inform autonomy level recommendations.

Records success and failure rates per: domain, skill, action type, and risk level. Periodically analyzes trends and generates recommendations: "Skill X has been invoked 50 times with 100% success rate at autonomy level 2; consider promoting to level 3." Recommendations require explicit user approval to take effect.

Also monitors for negative trends: if a previously reliable skill starts failing, the tracker can recommend autonomy reduction (with user confirmation).

**Public Interface**:
- `record_outcome(action: str, domain: str, skill: str, success: bool) -> None`
- `get_trust_report() -> TrustReport`
- `get_recommendations() -> list[TrustRecommendation]`
- `apply_recommendation(rec_id: RecommendationId) -> None`

## 3. Data Models

### PolicyRule
- `rule_id`: string
- `domain`: string | "*" (which domain this applies to)
- `action_type`: string | "*" (which action types)
- `skill_id`: string | None (specific skill, if applicable)
- `condition`: PolicyCondition (path pattern, host pattern, time window, etc.)
- `decision`: enum (allow, deny, require_approval)
- `priority`: int (higher priority rules override lower)
- `source`: enum (default, user_config, trust_escalation, standing_approval)
- Storage: YAML config + in-memory cache.

### AuditEntry
- `entry_id`: UUID
- `timestamp`: datetime
- `sequence_number`: int (monotonic, for ordering)
- `previous_hash`: string (hash of prior entry, for tamper detection)
- `entry_hash`: string
- `actor`: string (domain/component that performed the action)
- `action_type`: string
- `action_details`: dict
- `policy_decision`: PolicyDecision
- `outcome`: enum (success, failure, denied, timeout)
- `side_effects`: list[SideEffect]
- `mission_id`: UUID | None
- `task_id`: UUID | None
- Storage: Append-only SQLite with hash chain.

### ApprovalRequest
- `request_id`: UUID
- `created_at`: datetime
- `action`: ProposedAction
- `reasoning`: string (why the agent wants to do this)
- `expected_outcome`: string
- `risk_assessment`: string
- `status`: enum (pending, approved, denied, expired)
- `response_at`: datetime | None
- `responder`: string | None (user or auto-timeout)
- `approval_scope`: ApprovalScope | None
- Storage: SQLite.

### ApprovalScope
- `scope_type`: enum (single, batch, standing)
- `batch_filter`: dict | None (for batch: what other actions are auto-approved)
- `standing_rule`: PolicyRule | None (for standing: new rule to add)
- `expires_at`: datetime | None

### TrustRecommendation
- `recommendation_id`: UUID
- `domain`: string
- `skill_id`: string | None
- `current_level`: AutonomyLevel
- `recommended_level`: AutonomyLevel
- `evidence`: TrustEvidence (success rate, sample size, time period)
- `status`: enum (pending, applied, dismissed)
- Storage: SQLite.

## 4. Interface Contracts

### Control Plane → All Domains (synchronous check, must be fast)
```python
# Every domain calls this before executing any action
control.check_permission(action: ProposedAction) -> PolicyDecision
# Returns: allow, deny(reason), require_approval, allow_with_logging
```

### Control Plane → All Domains (async logging)
```python
# Every domain calls this after any significant action
control.log_action(entry: AuditEntry) -> None
```

### Control Plane → Agent Core (approval workflow)
```python
# Core requests approval when PolicyDecision is require_approval
control.request_approval(request: ApprovalRequest) -> ApprovalResult
# Blocks until user responds or timeout
```

### Control Plane → Agent Core (emergency controls)
```python
# Core must respond to these immediately
control.on_pause() -> None
control.on_resume() -> None
control.on_kill_task(task_id: str) -> None
control.on_shutdown() -> None
```

### Control Plane → Dashboard consumers (HTTP API)
```
GET /status, /missions, /tasks, /approvals, /audit, /health, /skills, /memory/stats
POST /approvals/:id/approve, /approvals/:id/deny
POST /emergency/pause, /emergency/resume, /emergency/kill/:task_id
```

## 5. State Management

**Policy State**: Rules are loaded from YAML config into an in-memory rule set on startup. Hot-reload watches config files for changes and re-evaluates. Invalid rules are rejected; the previous rule set remains active.

**Approval State**: Pending requests persist in SQLite. On restart, expired requests are auto-denied. Active requests are re-surfaced.

**Audit State**: Append-only. Never modified. Rotation moves old entries to archive files. The hash chain is validated on startup to detect corruption.

**Trust State**: Performance metrics accumulate in SQLite. Recommendations are generated periodically and persist until applied or dismissed.

**Recovery**: The Control Plane is the first component to initialize. It loads config, validates the audit log hash chain, re-surfaces pending approvals, and signals readiness before any other domain starts. If the Control Plane fails to initialize, the entire daemon refuses to start (fail-safe).

## 6. Design Patterns

- **Interceptor/Middleware Pattern**: Policy Engine acts as a middleware that every action passes through.
- **Chain of Responsibility**: Policy rules are evaluated in priority order; first matching rule determines the decision.
- **Event Sourcing**: Audit log is an append-only event store. System state can theoretically be reconstructed from the log.
- **Observer Pattern**: Trust Escalation Tracker observes outcomes from all domains.
- **Strategy Pattern**: Approval notification uses pluggable strategies (terminal, notification, API) based on available channels.
- **Fail-Safe Defaults**: Any error in policy evaluation defaults to `require_approval` (most restrictive), not `allow`.

## 7. Phased Rollout

**Phase 1 (MVP)**: Policy Engine with basic autonomy levels (observe, suggest, act-within-bounds). Audit Logger (SQLite, no hash chain yet). Approval workflow (terminal-only prompts). Emergency controls (SIGINT pause, SIGTERM shutdown). Config Manager (YAML loading, validation, no hot-reload). Dashboard API (basic /status and /audit endpoints). No Trust Escalation.

**Phase 2 (Full)**: Hash chain audit log for tamper detection. Batch and standing approval support. Full Dashboard API. Desktop notification approval channel. Trust Escalation Tracker with recommendations. Hot-reload configuration. Per-skill and per-domain autonomy overrides. Filesystem rollback via side-effect tracking.

**Phase 3 (Advanced)**: Tauri UI integration for approvals and monitoring. Natural language policy definitions ("let the agent send Slack messages only during business hours"). Predictive approval (anticipate what the agent will need approval for and batch-prompt the user). Multi-user support (different users with different autonomy policies). Audit log analytics (trends, anomaly detection).

## 8. Key Tradeoffs

**In-process policy evaluation vs. separate policy service**: Chose in-process. A separate service would provide better isolation but adds IPC latency to the hot path. Policy evaluation must be sub-millisecond; in-process function calls are the only way to guarantee this. The tradeoff is that a bug in the policy engine could theoretically affect the main process, but this is mitigated by keeping the policy engine stateless and well-tested.

**Hash chain audit log vs. simple append-only**: Chose hash chain for Phase 2. Simple append-only is sufficient for Phase 1 and much simpler. Hash chains add tamper detection, which matters as the agent gains more autonomy and the audit trail becomes more important for trust.

**Blocking approval vs. async approval**: Chose blocking (the requesting component waits for the approval result). Async approval (continue with other tasks while waiting) would be more efficient but dramatically more complex (task state must handle partial completion). Blocking is simpler and keeps the approval gate a hard gate. The Task Queue Manager can schedule other independent tasks while one is blocked on approval.

**YAML config vs. database config**: Chose YAML. Human-readable, version-controllable, diffable. Database config would be easier for programmatic updates but harder for users to inspect and edit manually. YAML strikes the right balance for a power-user tool.

## 9. Open Questions

- Should the audit log support structured queries (SQL-like) or just basic filtering? Structured queries add complexity but enable powerful analysis.
- How should approval timeouts work for long-running missions? If the user is away for 8 hours, should pending approvals expire and fail the task, or queue indefinitely?
- What is the right granularity for trust tracking? Per-skill? Per-action-type? Per-domain? Too granular creates noise; too coarse misses important patterns.
- Should the Dashboard API support WebSocket for real-time updates, or is polling sufficient for Phase 2?
- How should the Control Plane handle the case where the agent's reasoning suggests it should bypass safety controls? (Answer: it must not. But the architecture needs to make this impossible, not just inadvisable.)
