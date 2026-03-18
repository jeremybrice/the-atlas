# Mission Brief

**Playbook:** feature-build
**Design Doc:** docs/plans/2026-03-18-control-plane-completion-design.md
**Implementation Plan:** docs/plans/2026-03-18-control-plane-completion.md
**Created:** 2026-03-18

## Requirements Summary

1. **Emergency Controls** — EmergencyController class with pause/resume/kill operations. Wire into DaemonLoop (3 new socket commands: pause, resume, kill) and ExecutionLoop (asyncio.Event gating before each task, cancellation checks). Add `atlas daemon pause/resume/kill` CLI commands. Add 3 dashboard endpoints (POST /api/emergency/pause, /resume, /kill).

2. **Batch + Standing Approval Rules** — New `approval_rules` SQLite table. ApprovalRuleStore class with fnmatch glob-based matching, risk level comparison, path prefix matching, and expiration pruning. Wire into ApprovalWorkflow (check standing rules before terminal prompt, add `always/never` terminal options that create rules, add `request_batch_approval()` method). Add `atlas rules list/add/remove` CLI commands. Add 3 dashboard endpoints (GET/POST/DELETE /api/approvals/rules).

3. **Trust Recommendations** — New `trust_recommendations` SQLite table. TrustRecommendation dataclass. TrustTracker gains `create_recommendation()`, `list_recommendations()`, `resolve_recommendation()` methods. ExecutionLoop collects TrustOutcome signals during execution and creates recommendations post-mission. CLI prints post-mission trust summary with y/n/select prompts. Add `atlas trust recommendations/accept/dismiss/status` CLI commands. Add 4 dashboard endpoints.

4. **Full Dashboard API** — Refactor DashboardServer constructor to accept optional emergency_controller, approval_rule_store, trust_tracker, config. Components return 501 if None. Add endpoints: GET /api/tasks, GET /api/health, GET /api/config, GET /api/connectors. Enhance GET /api/status with paused, active_task_id, standing_rules_count. Enhance GET /api/memory/stats with embedding_count. Total: 20 endpoints.

5. **Wiring** — Wire all new components into both `_run_goal` (inline CLI) and `_run_daemon` (background daemon) paths in cli.py. Share EmergencyController instance between DaemonLoop and ExecutionLoop.

## Key Files

**Create:**
- `src/atlas/control/emergency.py` — EmergencyController class
- `src/atlas/control/approval_rules.py` — ApprovalRuleStore + glob matching

**Modify:**
- `src/atlas/contracts/types.py` — Add ApprovalRule, TrustRecommendation dataclasses
- `src/atlas/memory/store.py` — Add approval_rules and trust_recommendations table schemas
- `src/atlas/control/approval.py` — Wire rule store, batch approval, always/never prompts
- `src/atlas/control/trust.py` — Add recommendation create/list/resolve methods
- `src/atlas/core/loop.py` — Pause gating, trust signal collection, cancellation checks
- `src/atlas/core/missions.py` — Add trust_recommendations field to Mission
- `src/atlas/daemon/loop.py` — pause/resume/kill command handlers, accept EmergencyController
- `src/atlas/integrations/dashboard.py` — Refactor constructor, add 14 new endpoints
- `src/atlas/cli.py` — daemon pause/resume/kill, rules group, trust group, post-mission summary, full wiring

**Test files to create:**
- `tests/unit/control/test_emergency.py`
- `tests/unit/control/test_approval_rules.py`
- `tests/unit/control/test_trust_recommendations.py`
- `tests/unit/core/test_loop_emergency.py`
- `tests/integration/test_control_plane_completion.py`

**Test files to modify:**
- `tests/unit/daemon/test_daemon_loop.py`
- `tests/unit/control/test_approval.py`
- `tests/unit/integrations/test_dashboard.py`

## Test Command

```bash
source .venv/bin/activate && pytest tests/ -v
```

Linter:
```bash
source .venv/bin/activate && ruff check src/ tests/
```

## Developer Callouts

- **Python 3.12+** — use `str | None` syntax, no `from __future__ import annotations` needed in new files
- **Real SQLite in tests** — use `tmp_path` fixtures, no database mocks
- **ClaudeCodeBridge is the only mock** — everything else uses real implementations
- **Integration-focused testing** — unit test complex logic only
- **Absolute imports only** — `from atlas.x import Y`, no relative cross-domain imports
- **Error hierarchy** — all errors extend `RetriableError` or `FatalError` from `contracts/errors.py`
- **correlation_id** — propagated via `ExecutionContext` through all cross-domain calls
- **Existing tests must not break** — 273 tests currently passing

## Success Criteria

1. All 4 slices implemented end-to-end (schema → logic → CLI → dashboard)
2. EmergencyController pause/resume/kill works via daemon socket, CLI, and dashboard
3. Standing approval rules auto-approve/deny matching actions without terminal prompts
4. Batch approval presents grouped actions when multiple need approval
5. Trust recommendations created post-mission, surfaced in CLI summary, queryable via `atlas trust`
6. Dashboard API has 20 functioning endpoints (existing + new)
7. Full test suite passes (273+ tests, including new ones)
8. Linter passes (`ruff check src/ tests/`)
9. All new components default to None so existing code paths are unaffected
