# Mission Brief

**Playbook:** feature-build
**Design Doc:** docs/plans/2026-03-18-dashboard-ui-design.md
**Implementation Plan:** docs/plans/2026-03-18-dashboard-ui-implementation.md
**Created:** 2026-03-18

## Requirements Summary

1. Create `src/atlas/integrations/dashboard_ui.html` — single-file frontend using Alpine.js 3.x (CDN) + Tailwind CSS 3.x (CDN) + JetBrains Mono font (CDN)
2. Add `GET /` route to `DashboardServer` in `src/atlas/integrations/dashboard.py` that serves the HTML file
3. Persistent status bar with three rows: state/uptime/active task, health indicators (4 dots), goal input + emergency controls (pause/resume/kill)
4. 8 tabbed content sections: Missions (expandable to show tasks), Skills (card grid), Trust (records table + recommendation cards with accept/dismiss), Rules (add form + table with remove), Audit (scrollable table), Memory (3 stat cards), Connectors (status cards), Config (read-only key-value)
5. Auto-polling: 3s for status bar (`/api/status` + `/api/health`), 5s for active tab; inactive tabs not polled; polling pauses on browser tab hidden (Page Visibility API)
6. All interactive actions via `fetch()` to existing `/api/*` endpoints with inline feedback that fades after 2 seconds
7. Dark terminal aesthetic: `#0a0a0a` bg, `#141414` cards, `#00ff88` green accent, `#ffaa00` amber, `#ff4444` red, 4px border radius
8. No modals, no popups, no build step, no npm, no WebSocket

## Key Files

- `src/atlas/integrations/dashboard.py` — Existing dashboard API server; add `GET /` route and `_serve_ui` handler
- `src/atlas/integrations/dashboard_ui.html` — New file: the entire frontend (HTML + Alpine.js + Tailwind)
- `src/atlas/cli.py:615-633` — Where dashboard app is mounted into webhook HTTP server (read-only context)
- `tests/unit/integrations/test_dashboard.py` — Existing tests; add test for `GET /` serving HTML
- `config/default.yaml` — Default config (read-only reference for config tab display)
- `CLAUDE.md` — Project conventions

## Test Command

```bash
source .venv/bin/activate && pytest tests/ -v
```

Linter:
```bash
source .venv/bin/activate && ruff check src/ tests/
```

## Developer Callouts

- **Python 3.12+** — use `str | None` syntax, no `from __future__ import annotations`
- **Real SQLite in tests** — use `tmp_path` fixtures, no database mocks
- **ClaudeCodeBridge is the only mock** — everything else uses real implementations
- **Absolute imports only** — `from atlas.x import Y`, no relative cross-domain imports
- **Existing tests must not break** — 317 tests currently passing
- The HTML file is the bulk of the work; the Python change is minimal (one route + one handler)

## Success Criteria

1. Opening `http://localhost:8484/` in a browser when the daemon is running with `webhook.enabled=true` and `dashboard_enabled=true` shows the full dashboard
2. Status bar displays live daemon state, uptime, health, and provides working goal input and emergency controls
3. All 8 tabs render correctly with data from the API
4. Interactive controls (submit goal, pause/resume/kill, trust accept/dismiss, rule add/remove) work and show inline feedback
5. Auto-polling refreshes data without manual reload
6. All existing tests continue to pass, plus new test for `GET /` route
7. Dark terminal command-center aesthetic matches the design doc color scheme
