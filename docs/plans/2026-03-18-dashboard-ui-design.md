# ATLAS Dashboard UI Design

## Overview

A single-file web dashboard served by the existing aiohttp daemon at `http://localhost:8484/`. Provides real-time monitoring, admin controls, and a demo-ready visualization of the ATLAS autonomous agent system.

## Architecture

- **File:** `src/atlas/integrations/dashboard_ui.html`
- **Served by:** aiohttp at `GET /` via a new handler in `dashboard.py`
- **Frontend stack:** Alpine.js (CDN) + Tailwind CSS (CDN), no build step
- **API calls:** `fetch()` to same-origin `/api/*` endpoints
- **Auto-polling:** 3s for status bar, 5s for active tab content

No npm, no Node.js, no bundler. One HTML file with inline JS and Tailwind utility classes.

## Visual Style

Dark terminal command-center aesthetic.

| Element           | Value                                      |
|-------------------|--------------------------------------------|
| Background        | `#0a0a0a` (near-black)                     |
| Card/panel bg     | `#141414` with `#1a1a1a` borders           |
| Text              | `#e0e0e0` (light gray), monospace font     |
| Font              | JetBrains Mono (CDN) or system monospace   |
| Accent (healthy)  | `#00ff88` (terminal green)                 |
| Accent (warning)  | `#ffaa00` (amber)                          |
| Accent (error)    | `#ff4444` (red)                            |
| Border radius     | 4px                                        |

## Layout

```
+-------------------------------------------------------------+
|  STATUS BAR (always visible)                                |
|  Row 1: State indicator, uptime, active task                |
|  Row 2: Health dots (DB, Skills, Memory, Emergency)         |
|  Row 3: Goal input + submit, Pause/Resume/Kill buttons      |
+-------------------------------------------------------------+
|  TABS: Missions | Skills | Trust | Rules | Audit | Memory   |
|        | Connectors | Config                                |
+-------------------------------------------------------------+
|                                                             |
|  TAB CONTENT (swaps based on active tab)                    |
|                                                             |
+-------------------------------------------------------------+
```

### Status Bar (persistent)

Three rows, always visible at the top:

1. **State row:** Green/amber dot + "Running"/"Paused", uptime counter, active task ID (or "Idle")
2. **Health row:** Four small indicators for database, skill_registry, memory, emergency. Green dot = ok, red dot = error.
3. **Controls row:** Text input for goal submission + "Execute" button. Pause, Resume, and Kill Task buttons.

### Tabs

8 tabs, always accessible. Active tab highlighted with green underline/text.

## Tab Content

### Missions & Tasks

- Table of recent missions (last 50): goal text, status badge (color-coded), created_at, updated_at
- Click a mission row to expand inline, showing its tasks
- Task rows: description, skill_id, status badge, result snippet
- Status colors: green=completed, amber=executing/pending, red=failed, gray=cancelled

### Skills

- Card grid: skill name, description, risk level badge, tags as pills
- Risk badge colors: green=low, amber=medium, orange=high, red=critical
- Sorted alphabetically by name

### Trust & Autonomy

Two stacked sub-sections:

- **Trust Records table:** skill_id, successes, failures, success rate (computed), consecutive_successes, autonomy_override, last_outcome
- **Pending Recommendations:** Cards with skill, direction (escalate/demote), evidence summary, and [Accept] / [Dismiss] action buttons

### Approval Rules

- "Add Rule" form at top: skill pattern input, risk dropdown, decision dropdown (allow/deny), description input, [Add] button
- Table below: rule_id, match_skill, match_risk, decision badge, description, expires_at, [Remove] button per row

### Audit Log

- Scrollable table: timestamp, action_type, actor, outcome badge, mission_id
- Most recent first, limit 100 entries
- Auto-refreshes via polling

### Memory

- Three large stat cards with big monospace numbers: Episode Count, Mission Count, Embedding Count

### Connectors

- Card per connector: name, status indicator (green=connected, red=disconnected), owner/repo if configured
- Currently only GitHub connector

### Config

- Read-only key-value display grouped by category
- Categories: autonomy, memory, skills, trust, observation, reactive, mcp, webhook
- Monospace rendering, looks like a config file

## Polling Strategy

| Target          | Endpoint(s)                          | Interval |
|-----------------|--------------------------------------|----------|
| Status bar      | `/api/status` + `/api/health`        | 3s       |
| Active tab      | Tab-specific endpoint(s)             | 5s       |
| Inactive tabs   | Not polled                           | --       |

Polling pauses when browser tab is hidden (Page Visibility API).

## Interactive Actions

| Action               | Method | Endpoint                                | Feedback                        |
|----------------------|--------|------------------------------------------|---------------------------------|
| Submit Goal          | POST   | `/api/goal`                              | Inline flash: success/error     |
| Pause Daemon         | POST   | `/api/emergency/pause`                   | Status bar updates on next poll |
| Resume Daemon        | POST   | `/api/emergency/resume`                  | Status bar updates on next poll |
| Kill Task            | POST   | `/api/emergency/kill`                    | Prompt for task_id, inline flash|
| Accept Recommendation| POST   | `/api/trust/recommendations/{id}/accept` | Card updates inline             |
| Dismiss Recommendation| POST  | `/api/trust/recommendations/{id}/dismiss`| Card updates inline             |
| Add Rule             | POST   | `/api/approvals/rules`                   | Table refreshes                 |
| Remove Rule          | DELETE | `/api/approvals/rules/{id}`              | Row removed                     |

All feedback is inline (brief text that fades after 2 seconds). No modals or popups.

## Integration Changes

### `src/atlas/integrations/dashboard.py`

Add one route and handler:

```python
app.router.add_get("/", self._serve_ui)
```

Handler reads `dashboard_ui.html` from the package directory and serves it with `content-type: text/html`.

### No config changes needed

The dashboard UI is served when `webhook.enabled` and `webhook.dashboard_enabled` are both `true` — same as the existing API.

## What This Does NOT Include

- WebSocket support (polling is sufficient for agent operation cadence)
- Authentication (assumes local/trusted network, same as current API)
- Offline/PWA support
- Dark/light theme toggle (dark only)
- Mobile responsive layout (desktop-first, monitor use case)
