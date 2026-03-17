# ATLAS Phase 3 Implementation Design

**Date:** 2026-03-13
**Status:** Approved
**Depends on:** Phase 2 (daemon, reactive execution, skill forge, procedural memory)

## Overview

Phase 3 connects ATLAS to the outside world and makes it smarter over time. This design reorganizes the 10 vision features into 5 implementation stages based on dependency analysis and user decisions.

### Key Design Decisions

- **Credential Vault pulled to Stage A** — all connectors need secure credential storage from day one
- **Webhook Ingestion folded into Stage B** — connectors need real-time event reception immediately, not as a deferred optimization
- **Dashboard API uses HTTP on localhost** — standard HTTP on 127.0.0.1 for browser/curl compatibility
- **MCP server discovery via config file only** — explicit, predictable, no auto-scanning
- **Vector embeddings use local model** — `all-MiniLM-L6-v2` with Metal acceleration on M4 Macs
- **Multi-agent communication via shared SQLite** — WAL mode for concurrent access, already used for memory

## Stage Summary

| Stage | Features | Theme | Status |
|-------|----------|-------|--------|
| **A** | Trust Escalation + MCP Bridge + Credential Vault | Foundation: autonomy, tool expansion, secrets | Complete |
| **B** | GitHub Connector + Webhook Ingestion + Dashboard API | First integration + visibility | Complete |
| **D** | Vector Search + Multi-Agent Coordination | Intelligence + parallelism | Next |
| **E** | Browser Automation | Niche web interaction | Planned |
| **C** | Slack Connector + Jira Connector | Expand integration surface | Deferred |

> **Order change (2026-03-17):** Stage C deferred until after D and E. The Slack/Jira connectors are additional implementations of existing ConnectorABC infrastructure — no downstream dependencies. Deferral lets the connector layer stabilize under real GitHub usage before stamping out more implementations.

---

## Stage A: Trust Escalation + MCP Bridge + Credential Vault

### Trust Escalation

Tracks per-skill success/failure rates. After repeated successes, suggests promoting a skill's autonomy level. Failure spikes trigger automatic demotion. User explicitly approves all escalations.

**New files:**
- `src/atlas/control/trust.py` — `TrustTracker` class

**Modified files:**
- `src/atlas/control/policy.py` — accept per-skill autonomy overrides from TrustTracker
- `src/atlas/contracts/types.py` — trust record dataclass

**Behavior:**
- 10 consecutive successes → suggest escalation (requires user approval via `ApprovalWorkflowEngine`)
- 3 failures in 10 invocations → auto-demote (safety bias, logged to audit)
- Trust data persisted in SQLite
- Thresholds configurable in `default.yaml`

### MCP Bridge

Connects to MCP servers defined in config, enumerates their tools, auto-registers each as an ATLAS skill.

**New files:**
- `src/atlas/integrations/mcp.py` — `MCPBridge`, `MCPSkillAdapter`

**Modified files:**
- `config/default.yaml` — MCP server list: `[{name, command, args}]` or `[{name, url}]`
- `src/atlas/daemon/loop.py` — connect MCP on daemon start, disconnect on stop

**Behavior:**
- On daemon start, connects to all configured MCP servers
- Enumerates tools → registers each as skill with `risk_level=HIGH`
- MCP tool parameters → skill `input_schema`; results → `SkillResult`
- Session lifecycle managed by daemon

### Credential Vault

Encrypted local storage for API keys, OAuth tokens, with automatic refresh.

**New files:**
- `src/atlas/integrations/vault.py` — `CredentialVault` class

**Modified files:**
- `src/atlas/cli.py` — `atlas vault set/list/delete` commands

**Dependencies:** `cryptography`, `keyring`

**Behavior:**
- `vault.store(service, key, value)` / `vault.get(service, key)` API
- OAuth tokens with `expires_at` field; `vault.get_or_refresh(service)` for auto-refresh
- Encryption via `cryptography.Fernet`, key derived via PBKDF2 from passphrase stored in OS keychain via `keyring`
- Credentials in separate SQLite table

---

## Stage B: GitHub Connector + Webhook Ingestion + Dashboard API

### GitHub Connector

Reacts to GitHub events (PR opened, CI failed, issue assigned) and takes actions (comment, approve, create branches).

**New files:**
- `src/atlas/integrations/connector.py` — `ConnectorABC` base class (authenticate, handle_event, execute_action, rate limiting)
- `src/atlas/integrations/connectors/github.py` — `GitHubConnector`
- `src/atlas/integrations/entity_mapper.py` — `EntityMapper` (bidirectional ATLAS ↔ external ID mapping)

**Dependencies:** `httpx` (already used)

**Behavior:**
- Authenticates via GitHub App or PAT (credentials from vault)
- Incoming webhook events normalized into `ObservationEvent` → existing `ObservationEngine`
- Outbound actions go through `ControlPlaneInterface.check_permission()` with appropriate risk levels
- Rate limiting built into `ConnectorABC`

### Webhook Ingestion

HTTP endpoint receiving webhook payloads from external services, routing into the observation pipeline.

**New files:**
- `src/atlas/integrations/webhook.py` — `WebhookServer` (lightweight `aiohttp` on `127.0.0.1`)
- `src/atlas/integrations/event_bridge.py` — `EventBridge` (normalizes raw payloads → `ObservationEvent`)

**Dependencies:** `aiohttp`

**Behavior:**
- Runs as part of daemon process (start/stop with daemon lifecycle)
- Each connector registers webhook routes and payload parser with EventBridge
- Validates webhook signatures (e.g., GitHub HMAC) before processing
- Default port configurable in `default.yaml`

### Dashboard API

HTTP API on `127.0.0.1` serving JSON for monitoring and control.

**New files:**
- `src/atlas/integrations/dashboard.py` — `DashboardServer` (`aiohttp` app)

**Endpoints:**
- `GET /status` — daemon health, uptime, active watchers
- `GET /missions` — mission list and history
- `GET /skills` — skill registry with usage stats
- `GET /memory/stats` — episode count, procedure success rates
- `GET /audit` — paginated audit log
- `POST /goal` — submit a goal to the daemon

**Behavior:**
- Shares `aiohttp` app with webhook server (or separate configurable port)
- Read-only for monitoring; `POST /goal` goes through policy engine
- No authentication (localhost only)

---

## Stage C: Slack Connector + Jira Connector

### Slack Connector

**New files:**
- `src/atlas/integrations/connectors/slack.py` — `SlackConnector` implementing `ConnectorABC`

**Behavior:**
- Authenticates via Bot Token (stored in vault)
- Incoming: Slack Events API webhooks → EventBridge → ObservationEvent (mentions, DMs, pattern matches)
- Outgoing: Post messages, reactions, thread replies — policy-gated
- Rate limiting per Slack's tier system
- Entity mapping: Slack channel/user IDs ↔ ATLAS entities

### Jira Connector

**New files:**
- `src/atlas/integrations/connectors/jira.py` — `JiraConnector` implementing `ConnectorABC`

**Behavior:**
- Authenticates via API token or OAuth (stored in vault)
- Incoming: Jira webhooks (issue created, status changed) → observation pipeline
- Outgoing: Create issues, update status, add comments — policy-gated
- Entity mapping: Jira issue keys (e.g., `PROJ-123`) ↔ ATLAS task/mission IDs
- Supports Jira Cloud and Server (configurable base URL)

Both connectors reuse Stage B infrastructure: `ConnectorABC`, `EventBridge`, `WebhookServer`, `EntityMapper`, `CredentialVault`.

---

## Stage D: Vector Search + Multi-Agent Coordination

### Vector Search

Replaces keyword-based episode/memory search with semantic similarity using local embeddings.

**New files:**
- `src/atlas/memory/embeddings.py` — `EmbeddingProvider` (wraps `sentence-transformers`)
- `src/atlas/memory/vector_store.py` — `VectorStore` (SQLite + numpy vector storage and cosine similarity)

**Modified files:**
- `src/atlas/memory/episodic.py` — compute embeddings on episode save
- `src/atlas/memory/retrieval.py` — hybrid retrieval combining keyword + semantic similarity

**Dependencies:** `sentence-transformers`, `numpy`

**Behavior:**
- Model: `all-MiniLM-L6-v2` (~80MB, Metal-accelerated on M4 Macs)
- Embeddings computed on episode save, stored alongside episode records
- Search: query → embed → cosine similarity → top-K
- Hybrid scoring: `0.6 * semantic + 0.4 * keyword` (configurable)
- Lazy model loading (first use, not startup)
- Migration: batch-embed existing episodes on first vector-search-enabled run

### Multi-Agent Coordination

Multiple ATLAS instances collaborating on goals via shared SQLite.

**New files:**
- `src/atlas/core/agents.py` — `AgentRegistry` (active agents, capabilities, assignments)
- `src/atlas/core/work_splitter.py` — `WorkSplitter` (mission decomposition, parallel sub-task assignment)
- `src/atlas/core/conflicts.py` — `ConflictResolver` (concurrent file operation conflict detection)

**Behavior:**
- Each agent registers in shared `agents` table with heartbeat
- Work splitting: mission planner identifies independent sub-tasks → assigns to available agents
- Communication: shared `messages` table (polling, ~1s interval)
- File conflicts: advisory locks in SQLite; conflicting agents wait
- Agent discovery: capability advertisement (skills, current load)
- Graceful degradation: missed heartbeats → task reassignment

---

## Stage E: Browser Automation

Playwright-based web interaction for testing, scraping, and web-only services.

**New files:**
- `src/atlas/skills/browser.py` — `BrowserSkill` (high-level browser ops registered as ATLAS skills)
- `src/atlas/env/browser.py` — `BrowserSession` (Playwright lifecycle, navigation, interaction)

**Skills exposed:**
- `browser.navigate` — go to URL, return content/screenshot
- `browser.click` — click element by selector
- `browser.fill` — fill form fields
- `browser.screenshot` — capture page screenshot
- `browser.extract` — extract structured data via selectors

**Dependencies:** `playwright` (optional: `pip install atlas[browser]`)

**Behavior:**
- Headless by default; configurable for debugging
- All browser actions `risk_level=HIGH` — policy-gated
- Session per mission, closed on mission end
- Screenshots saved to workspace for audit

---

## Dependency Graph

```
Stage A: [Trust Escalation] [MCP Bridge] [Credential Vault]       ✅ Complete
              │                    │              │
              ▼                    ▼              ▼
Stage B: [GitHub Connector] ← [Webhook Ingestion] [Dashboard API] ✅ Complete

Stage D: [Vector Search]     [Multi-Agent]                         ← Next

Stage E: [Browser Automation]

Stage C: [Slack Connector]   [Jira Connector]                      Deferred
```

## New Dependencies Summary

| Package | Stage | Purpose |
|---------|-------|---------|
| `cryptography` | A | Fernet encryption for credential vault |
| `keyring` | A | OS keychain access for vault master key |
| `aiohttp` | B | Webhook server + dashboard API |
| `sentence-transformers` | D | Local embedding model |
| `numpy` | D | Vector operations |
| `playwright` | E | Browser automation (optional extra) |

## Testing Strategy

- **Trust Escalation:** Unit tests for threshold logic; integration test with PolicyEngine
- **MCP Bridge:** Mock MCP server for tool discovery and invocation
- **Credential Vault:** Unit tests for encrypt/decrypt; integration test with SQLite
- **Connectors:** Mock HTTP responses; integration tests with EventBridge → ObservationEngine pipeline
- **Webhook Server:** `aiohttp` test client for endpoint validation
- **Dashboard API:** `aiohttp` test client against real SQLite stores
- **Vector Search:** Unit tests for embedding + cosine similarity; integration with EpisodicMemoryStore
- **Multi-Agent:** Multi-process integration test with shared SQLite
- **Browser:** Mock Playwright for skill registration; optional E2E with real browser
