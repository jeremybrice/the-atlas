# Control Plane Completion — Design Document

**Date:** 2026-03-18
**Branch:** phase3-control-plane-completion (from phase3-stage-d1-vector-search)
**Approach:** Feature slices — each slice delivers end-to-end from schema through logic through CLI/API

## Scope

Four feature areas built as vertical slices:

1. **Graceful daemon controls** — pause/resume/kill via CLI + Unix socket + dashboard
2. **Batch + standing approval rules** — persistent rules, batch approve/deny, auto-approve matching requests
3. **Trust recommendations** — post-mission summary with prompts, persisted to DB, queryable via CLI + dashboard
4. **Full dashboard API** — emergency endpoints, approval management, health checks, task queue, config summary, connector health, agent state

### Out of Scope

- Audit log hash chains / tamper detection
- Signal handling (SIGINT/SIGTERM)
- Filesystem rollback
- Temporal rules / rate limits in PolicyEngine
- Config hot-reload / versioning
- Desktop notifications / Tauri UI

---

## Slice 1: Emergency Controls

### EmergencyController

New class in `src/atlas/control/emergency.py`. Wraps references to DaemonLoop and ExecutionLoop.

**Operations:**

- **`pause()`** — sets DaemonLoop to stop accepting new goals, sets a `_paused` asyncio.Event on ExecutionLoop. Running tasks finish; new tasks wait.
- **`resume()`** — clears the paused flag, restarts DaemonLoop goal acceptance.
- **`kill_task(task_id)`** — marks a specific in-flight task as CANCELLED and sets a cancellation flag the runtime checks.

### Daemon Protocol Extension

Three new commands in `DaemonLoop._handle_command`:

- `"pause"` → calls `EmergencyController.pause()`
- `"resume"` → calls `EmergencyController.resume()`
- `"kill"` (with `payload.task_id`) → calls `EmergencyController.kill_task()`

### ExecutionLoop Changes

- Add `_paused` asyncio.Event (set = running, cleared = paused)
- Before each task execution, `await self._paused.wait()`
- Add `_active_task_id` property for status reporting

### CLI Commands

- `atlas daemon pause` — sends pause command over Unix socket
- `atlas daemon resume` — sends resume command over Unix socket
- `atlas daemon kill <task_id>` — sends kill command over Unix socket

### Dashboard Endpoints

- `POST /api/emergency/pause`
- `POST /api/emergency/resume`
- `POST /api/emergency/kill` (body: `{"task_id": "..."}`)

### Status Enhancements

`_handle_status` response gains `"paused": bool` and `"active_task_id"` fields.

---

## Slice 2: Batch + Standing Approval Rules

### Database Schema

New table `approval_rules`:

```sql
CREATE TABLE IF NOT EXISTS approval_rules (
    rule_id TEXT PRIMARY KEY,
    rule_type TEXT NOT NULL,       -- "standing"
    match_skill TEXT NOT NULL,     -- skill_id glob pattern: "file.*", "*"
    match_risk TEXT NOT NULL,      -- max risk level: "low", "medium", "high", "*"
    match_path TEXT,               -- optional path prefix filter
    decision TEXT NOT NULL,        -- "allow" or "deny"
    created_at TEXT NOT NULL,
    expires_at TEXT,               -- NULL = permanent
    description TEXT
)
```

### ApprovalRule Dataclass

New in `contracts/types.py`:

```python
@dataclass
class ApprovalRule:
    rule_id: str = field(default_factory=new_id)
    rule_type: str = "standing"
    match_skill: str = "*"
    match_risk: str = "*"
    match_path: str | None = None
    decision: str = "allow"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str | None = None
    description: str = ""
```

### ApprovalRuleStore

New class in `src/atlas/control/approval_rules.py`:

- `add_rule(rule: ApprovalRule) → str` — inserts rule, returns rule_id
- `remove_rule(rule_id: str) → bool` — deletes rule
- `list_rules() → list[ApprovalRule]` — all non-expired rules
- `find_matching(action: ProposedAction) → ApprovalRule | None` — first matching rule by skill_id glob, risk_level, and path params. Expired rules pruned on access.

### ApprovalWorkflow Changes

Constructor gains `rule_store: ApprovalRuleStore | None = None`.

`request_approval()` flow becomes:

1. Check `auto_approve` / `auto_deny` (existing)
2. **Check standing rules** via `rule_store.find_matching(action)` → if match, return its decision
3. Fall through to terminal prompt (existing)

Terminal prompt gains new options:

```
Approve? (y/n/always/never):
```

- `always` → creates standing "allow" rule for that skill_id + risk_level
- `never` → creates standing "deny" rule for that skill_id + risk_level

### Batch Approval

New method `request_batch_approval(requests: list[ApprovalRequest]) → list[ApprovalResult]`.

Presents grouped actions:

```
[approval] 3 actions pending:
  1. file.read — Read config.yaml (LOW risk)
  2. file.write — Write output.json (MEDIUM risk)
  3. shell.execute — Run pytest (HIGH risk)
Approve all? (y/n/select):
```

- `y` → approve all
- `n` → deny all
- `select` → prompt individually

### ExecutionLoop Changes

When the next N consecutive tasks all need approval and no standing rule matches, collect them into a `_pending_approvals` list and call `request_batch_approval()`.

### CLI Commands

- `atlas rules list` — show all standing rules
- `atlas rules add --skill "file.*" --risk low --decision allow` — create a rule
- `atlas rules remove <rule_id>` — delete a rule

### Dashboard Endpoints

- `GET /api/approvals/rules` — list standing rules
- `POST /api/approvals/rules` — create a rule (body: rule fields)
- `DELETE /api/approvals/rules/{rule_id}` — delete a rule

---

## Slice 3: Trust Recommendations

### Database Schema

New table `trust_recommendations`:

```sql
CREATE TABLE IF NOT EXISTS trust_recommendations (
    recommendation_id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL,
    current_level TEXT NOT NULL,
    recommended_level TEXT NOT NULL,
    direction TEXT NOT NULL,          -- "escalate" or "demote"
    evidence TEXT NOT NULL,           -- JSON: {success_rate, sample_size, consecutive_successes, recent_failures}
    status TEXT NOT NULL DEFAULT 'pending',  -- "pending", "accepted", "dismissed"
    mission_id TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
)
```

### TrustRecommendation Dataclass

New in `contracts/types.py`:

```python
@dataclass
class TrustRecommendation:
    recommendation_id: str = field(default_factory=new_id)
    skill_id: str = ""
    current_level: str = ""
    recommended_level: str = ""
    direction: str = ""               # "escalate" or "demote"
    evidence: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    mission_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: str | None = None
```

### TrustTracker Changes

New methods:

- `create_recommendation(skill_id, direction, mission_id) → TrustRecommendation` — reads current TrustRecord to compute evidence, determines recommended level (escalate: OBSERVE→SUGGEST→ACT_WITHIN_BOUNDS, demote: reverse), inserts into trust_recommendations with status "pending"
- `list_recommendations(status="pending") → list[TrustRecommendation]`
- `resolve_recommendation(recommendation_id, accepted: bool) → None` — sets status to "accepted" or "dismissed"; if accepted, calls `set_autonomy_override()`

### ExecutionLoop Changes

1. After each skill invocation, call `trust_tracker.record_outcome()`
2. Collect `TrustOutcome` with `should_escalate=True` or `should_demote=True` into a `_trust_signals` list
3. After mission completes, call `trust_tracker.create_recommendation()` for each signal
4. Return recommendations alongside the mission result

### Post-Mission CLI Summary

After execution loop returns, if pending recommendations exist:

```
Trust recommendations based on this mission:
  1. file.read — promote to ACT_WITHIN_BOUNDS (15/15 successes)
  2. shell.execute — demote to OBSERVE (3 failures in last 5)
Accept recommendations? (y/n/select):
```

- `y` → accept all, apply overrides
- `n` → dismiss all
- `select` → prompt per recommendation

### CLI Commands

- `atlas trust recommendations` — list pending recommendations
- `atlas trust accept <id>` — accept and apply
- `atlas trust dismiss <id>` — dismiss
- `atlas trust status` — show all skill trust records

### Dashboard Endpoints

- `GET /api/trust/recommendations` — list (filterable by `?status=pending`)
- `POST /api/trust/recommendations/{id}/accept`
- `POST /api/trust/recommendations/{id}/dismiss`
- `GET /api/trust/records` — all trust records

---

## Slice 4: Full Dashboard API

### DashboardContext

Replace the growing constructor with a bundled context:

```python
@dataclass
class DashboardContext:
    db: DatabaseStore
    audit: AuditLogger
    registry: SkillRegistry
    config: AtlasConfig
    goal_handler: GoalHandler | None = None
    emergency_controller: EmergencyController | None = None
    approval_rule_store: ApprovalRuleStore | None = None
    trust_tracker: TrustTracker | None = None
```

Endpoints that depend on optional components return `501 Not Configured` if the component is None.

### Complete Endpoint List (20 total)

**Existing (unchanged):**
1. `GET /api/missions` — mission list
2. `GET /api/skills` — skill registry
3. `GET /api/audit` — audit log with limit
4. `POST /api/goal` — submit goal

**Enhanced:**
5. `GET /api/status` — add `paused`, `active_task_id`, `active_mission_id`, `connected_mcp_servers`, `standing_rules_count`
6. `GET /api/memory/stats` — add embedding count, working memory key count

**New from Slice 1 (emergency):**
7. `POST /api/emergency/pause`
8. `POST /api/emergency/resume`
9. `POST /api/emergency/kill`

**New from Slice 2 (approvals):**
10. `GET /api/approvals/rules`
11. `POST /api/approvals/rules`
12. `DELETE /api/approvals/rules/{rule_id}`

**New from Slice 3 (trust):**
13. `GET /api/trust/recommendations`
14. `POST /api/trust/recommendations/{id}/accept`
15. `POST /api/trust/recommendations/{id}/dismiss`
16. `GET /api/trust/records`

**New in Slice 4:**
17. `GET /api/tasks` — current mission's task queue. Optional `?mission_id=` filter, defaults to most recent active mission.
18. `GET /api/health` — domain health checks. Returns per-subsystem status: database (SELECT 1), daemon, http, skill_registry (count), memory (episode count), mcp (configured vs not), webhook (configured vs not). Exceptions → "error" with message.
19. `GET /api/config` — non-sensitive config summary. Returns autonomy_level, memory settings, skill list, observation watches, trust thresholds. Excludes API keys, vault passphrase, tokens.
20. `GET /api/connectors` — connector health. Lists configured connectors with status (authenticated, rate limit remaining, last event time). Initially just GitHub.

---

## File Impact Summary

### New Files

| File | Purpose |
|------|---------|
| `src/atlas/control/emergency.py` | EmergencyController class |
| `src/atlas/control/approval_rules.py` | ApprovalRuleStore + rule matching logic |
| `tests/unit/control/test_emergency.py` | EmergencyController tests |
| `tests/unit/control/test_approval_rules.py` | ApprovalRuleStore tests |
| `tests/unit/control/test_trust_recommendations.py` | TrustTracker recommendation tests |
| `tests/integration/test_control_plane_completion.py` | End-to-end integration tests |

### Modified Files

| File | Changes |
|------|---------|
| `src/atlas/contracts/types.py` | Add `ApprovalRule`, `TrustRecommendation`, `DashboardContext` |
| `src/atlas/memory/store.py` | Add `approval_rules` and `trust_recommendations` table schemas |
| `src/atlas/control/approval.py` | Wire rule store, add `always/never` prompt, add `request_batch_approval()` |
| `src/atlas/control/trust.py` | Add `create_recommendation()`, `list_recommendations()`, `resolve_recommendation()` |
| `src/atlas/core/loop.py` | Add `_paused` event, trust outcome collection, batch approval, post-mission recommendations |
| `src/atlas/daemon/loop.py` | Add `pause/resume/kill` handlers, `_paused` state, `EmergencyController` wiring |
| `src/atlas/integrations/dashboard.py` | Refactor to `DashboardContext`, add 14 new endpoints |
| `src/atlas/cli.py` | Add `atlas daemon pause/resume/kill`, `atlas rules`, `atlas trust` command groups, post-mission trust summary |

---

## Testing Strategy

- **Unit tests** for EmergencyController, ApprovalRuleStore, TrustTracker recommendations — real SQLite via `tmp_path`, no mocks
- **Unit tests** for enhanced ApprovalWorkflow with rule matching
- **Integration test**: full mission flow with standing rules auto-approving, trust recommendations generated and resolved
- **Dashboard endpoint tests** via `pytest-aiohttp`
- **Daemon socket protocol tests** for pause/resume/kill commands
- ClaudeCodeBridge mocked at boundary (only mock in the suite, per CLAUDE.md)
