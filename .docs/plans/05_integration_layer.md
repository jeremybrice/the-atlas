# Domain 5: Integration Layer — Detailed Goals

## Primary Mission
Design the bridge between ATLAS and the external service ecosystem. The Integration Layer manages connections to MCP servers, SaaS platforms (Jira, Slack, Google Drive, etc.), local tools, and any future service the agent needs to interact with. It handles authentication, protocol translation, connection lifecycle, rate limiting, and data normalization so that the rest of ATLAS works with consistent internal representations regardless of the external source.

## Goals

### G5.1: Universal Connector Architecture
Design a pluggable connector model where each external service is represented by a connector that implements a standard interface. Every connector must handle: authentication (OAuth, API keys, tokens, with secure credential storage), connection lifecycle (connect, health check, reconnect, disconnect), request/response translation (external formats ↔ ATLAS internal formats), rate limiting and backoff (respect service limits, queue requests when throttled), error handling (transient failures, auth expiration, service outages), and capability advertisement (what operations does this connector support?). New connectors should be addable without modifying the core integration framework.

### G5.2: MCP Server Integration
Design first-class support for Model Context Protocol servers. MCP is becoming the standard for LLM-tool integration, and ATLAS should be able to: discover and connect to MCP servers (local and remote), expose MCP tools as ATLAS skills (bridging the Skill Engine), use MCP resources as environment data sources, and potentially expose ATLAS capabilities as an MCP server itself (so other tools can use ATLAS). This is strategically important given the MCP-first platform direction you've been exploring at 365.

### G5.3: Service-Specific Connectors
Design connectors for the services most critical to your workflow:

- **Jira**: Read/write issues, transitions, comments, sprint data. Must understand your Jira structure (Initiatives → Epics → Stories). Support JQL queries and webhook-driven observation.
- **Slack**: Read channels/threads, send messages, react. Support the inbox scanning and activity monitoring patterns from existing Forge skills.
- **Google Drive**: Search, read, create, update documents. Support for Docs, Sheets, and file management.
- **GitHub/Git**: Repository operations, PR management, commit history, branch management. Critical for skill authoring and code-related tasks.
- **Local CLI Tools**: Integration with tools already installed on the system (npm, pip, docker, etc.)

Each connector should be designed as a reference implementation that demonstrates the connector pattern for future additions.

### G5.4: Credential Management
Design secure handling of authentication credentials across all connectors. Requirements: encrypted at-rest storage (not plaintext in config files), support for multiple credential types (OAuth tokens, API keys, SSH keys, certificates), automatic token refresh for OAuth flows, credential scoping (connector X can only use credential Y), and credential lifecycle management (rotation, expiration warnings, revocation). Must integrate with the Control Plane for audit trail of credential usage.

### G5.5: Data Normalization and Entity Mapping
Design how external data gets translated into ATLAS internal representations. A Jira ticket, a Slack message, and a Google Doc are all "external entities" that the agent might reference. The normalization layer must: define a common entity model for cross-service references, maintain bidirectional mappings (ATLAS entity ID ↔ external service ID), handle entity lifecycle (external entity updated/deleted), and support cross-service entity linking (this Jira ticket relates to that Slack thread). This normalized data feeds into the Memory System's semantic memory.

### G5.6: Event Bridge
Design how external service events flow into ATLAS's reactive processing. External events include: Jira ticket state changes, Slack messages in watched channels, Google Drive file modifications, GitHub PR reviews and CI results, and webhook deliveries from arbitrary services. The Event Bridge must: normalize events into a standard ATLAS event format, filter and route events to the appropriate observation channels, buffer events during high-volume periods, and deduplicate events (same change reported by multiple sources).

### G5.7: Forge Plugin Migration — Integration Aspects
Design how existing Forge plugins that wrap external services (slack-inbox-scanner, jira-activity-scanner, notion-writer) migrate into ATLAS connectors. The migration should: extract the service interaction logic from each plugin, repackage it as a proper ATLAS connector, preserve existing functionality and data formats, and upgrade the interaction patterns to use the new connector framework (benefiting from unified auth, rate limiting, error handling, etc.).

## Cross-Domain Dependencies
- **Agent Core**: Triggers integration actions as part of task execution. Receives external events for reactive processing.
- **Skill Engine**: Skills may invoke connectors for external operations. MCP tools become ATLAS skills. Connector capabilities are advertised to the skill registry.
- **Memory System**: External entity state persists in semantic memory. Credential metadata (not secrets) stored in memory. Connection history stored in episodic memory.
- **Environment Interface**: Network requests route through environment's network capability. Connector health is part of environment state model.
- **Control Plane**: All external interactions are logged. Credential access is audited. High-impact external actions (sending Slack messages, transitioning Jira tickets) may require approval.

## Key Constraints
- Must not store credentials in plaintext anywhere
- Must respect rate limits of all external services (no getting accounts banned)
- Must handle offline/disconnected operation gracefully (queue actions, retry when available)
- Connector failures must not crash the daemon or block other operations
- MCP integration should follow the official MCP specification closely (future-proofing)
- Must support the user adding new connectors without deep framework knowledge
