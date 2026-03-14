# ATLAS Phase 3 Vision

**Status:** Not started
**Depends on:** Phase 2 (daemon, reactive execution, skill forge, memory completion)

## What Phase 3 Builds

Phase 2 gave ATLAS autonomy (daemon), reactivity (observation engine), and learning (skill forge + procedural memory). Phase 3 connects it to the outside world and makes it smarter over time.

## Features

### Trust Escalation
The daemon currently requires approval for medium/high risk skills every time. Trust escalation tracks success/failure rates per skill and autonomy level. After repeated successes, the system auto-suggests raising autonomy for that skill. Spikes in failure rates trigger automatic reduction. User explicitly approves any escalation.

### Integration Layer
Pluggable connector architecture for external services. Each connector implements a standard ABC with auth, rate limiting, and error handling. Priority connectors:
- **GitHub** — react to PR events, CI failures, issue assignments via webhooks
- **Slack** — read channels, post messages, respond to mentions
- **Jira** — read/update issues, react to status changes

Also includes:
- **Credential Vault** — encrypted storage for API keys, OAuth tokens, automatic refresh
- **Event Bridge** — normalizes external service events into ATLAS ObservationEvents
- **Entity Mapper** — bidirectional mapping between ATLAS IDs and external service IDs

### MCP Bridge
First-class Model Context Protocol support. ATLAS can:
- Discover and connect to MCP servers (local and remote)
- Enumerate tools from connected servers
- Auto-register MCP tools as ATLAS skills (with appropriate risk levels)
- Manage MCP session lifecycle

This is strategically important — it lets ATLAS consume any MCP-compatible tool without writing custom connectors or forging skills.

### Dashboard API
Local HTTP or Unix socket API serving structured JSON for monitoring and control:
- Mission status and history
- Skill registry and usage stats
- Memory stats (episode count, procedure success rates)
- Daemon health (uptime, active watchers, recent events)
- Audit log viewer

### Multi-Agent Coordination
Multiple ATLAS instances collaborating on goals:
- Work splitting across agents
- Shared memory and communication
- Conflict resolution for concurrent file operations
- Agent discovery and capability advertisement

### Vector Embedding Search
Replace keyword-based episode/memory search with local vector embeddings:
- Local embedding model (no cloud dependency)
- Semantic similarity for episode retrieval
- Better context assembly for planning and reflection
- Cross-episode causal reasoning

### Browser Automation
Selenium or Playwright-based web interaction:
- Navigate pages, fill forms, click elements
- Screen capture and visual understanding
- Useful for testing web apps, scraping data, interacting with web-only services

### Webhook Ingestion
HTTP endpoint for receiving real-time events from external services:
- GitHub webhooks (push, PR, CI status)
- Slack events API
- Custom webhook sources
- Normalizes into ObservationEvents for the reactive pipeline

## Recommended Priority

1. **Trust escalation** — reduces friction immediately, makes the daemon usable hands-off
2. **MCP Bridge** — massive capability expansion with minimal code
3. **GitHub connector** — the most common developer workflow integration
4. **Dashboard API** — visibility into what the daemon is doing
5. **Credential Vault** — required for any authenticated external service
6. **Slack/Jira connectors** — expand integration surface
7. **Vector search** — improves memory quality
8. **Multi-agent** — advanced, needs all other pieces stable first
9. **Browser automation** — niche, defer unless specifically needed
10. **Webhook ingestion** — needed for real-time external events, pairs with connectors

## Key Architectural Decisions to Make

- HTTP vs Unix socket for dashboard API
- Which embedding model for vector search (and whether to require GPU)
- Connector plugin format (Python packages? Single files like forged skills?)
- MCP server discovery mechanism (config file? Auto-scan?)
- Multi-agent communication protocol (shared SQLite? Message passing?)
