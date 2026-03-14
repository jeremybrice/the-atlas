# Mission Brief

**Playbook:** feature-build
**Design Doc:** docs/plans/2026-03-13-phase3-stage-b.md
**Created:** 2026-03-14

## Requirements Summary

1. **WebhookConfig + aiohttp dependency** — Add `WebhookConfig` dataclass to `config.py`, aiohttp to `pyproject.toml`, webhook section to `default.yaml`
2. **entity_mappings SQLite table** — Add table to `DatabaseStore._create_tables()` for bidirectional ATLAS↔external ID mapping
3. **EntityMapper** — New `integrations/entity_mapper.py` with link/unlink/get_atlas_id/get_external_id CRUD
4. **ConnectorABC base class** — New `integrations/connector.py` with abstract authenticate/handle_event/execute_action + rate limiting
5. **GitHubConnector** — New `integrations/connectors/github.py` implementing ConnectorABC with event parser, comment/issue API actions
6. **EventBridge** — New `integrations/event_bridge.py` for normalizing webhook payloads into ObservationEvents with HMAC signature verification
7. **WebhookServer** — New `integrations/webhook.py` aiohttp server for receiving HTTP webhook payloads and routing through EventBridge

## Key Files

- `src/atlas/integrations/connector.py` — ConnectorABC
- `src/atlas/integrations/entity_mapper.py` — EntityMapper
- `src/atlas/integrations/event_bridge.py` — EventBridge
- `src/atlas/integrations/webhook.py` — WebhookServer
- `src/atlas/integrations/dashboard.py` — DashboardServer
- `src/atlas/integrations/connectors/github.py` — GitHubConnector
- `src/atlas/config.py` — WebhookConfig
- `src/atlas/memory/store.py` — entity_mappings table
- `src/atlas/daemon/loop.py` — HTTP app runner support
- `src/atlas/cli.py` — Webhook + dashboard wiring in daemon

## Test Command

`pytest tests/ -v`

## Developer Callouts

Follow CLAUDE.md conventions:
- Python 3.12+ with `str | None` syntax
- No `from __future__ import annotations` in new files
- src layout imports: `from atlas.x import Y`
- Errors extend `RetriableError` or `FatalError`
- Mock only `ClaudeCodeBridge`, use real SQLite with `tmp_path`

## Success Criteria

- All 11 tasks from the implementation plan are complete
- `WebhookServer` receives HTTP webhooks and routes through `EventBridge` to `ObservationEngine`
- `GitHubConnector` implements `ConnectorABC` with event parsing and GitHub API actions
- `DashboardServer` serves REST endpoints reading from existing SQLite stores
- `EntityMapper` provides bidirectional ATLAS↔external ID mapping
- `DaemonLoop` starts HTTP server alongside Unix socket server
- All new and existing tests pass (`pytest tests/ -v`)
- Lint clean (`ruff check src/ tests/`)
- Integration test demonstrates webhook→event pipeline end-to-end
