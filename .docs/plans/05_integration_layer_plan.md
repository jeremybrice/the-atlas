# Domain 5: Integration Layer — Architectural Design Plan

## 1. Architecture Overview

The Integration Layer bridges ATLAS to the external service ecosystem. It manages connections to Jira, Slack, Google Drive, GitHub, MCP servers, and any future service the agent needs. The architecture is built around a **pluggable Connector framework** where each service integration is a self-contained connector that implements a standard interface.

A **Credential Vault** provides secure storage, an **Event Bridge** normalizes incoming external events, and an **Entity Mapper** maintains bidirectional mappings between ATLAS internal identifiers and external service identifiers.

```
                    ┌──────────────────────────────┐
                    │     Integration Manager       │
                    │  (connector lifecycle,        │
                    │   routing, health monitoring) │
                    └──────────────┬───────────────┘
                                   │
       ┌───────────┬───────────────┼───────────────┬───────────┐
       │           │               │               │           │
  ┌────▼────┐ ┌────▼────┐  ┌──────▼──────┐  ┌─────▼─────┐ ┌──▼──┐
  │  Jira   │ │  Slack  │  │Google Drive │  │  GitHub   │ │ MCP │
  │Connector│ │Connector│  │ Connector   │  │ Connector │ │Bridge│
  └─────────┘ └─────────┘  └─────────────┘  └───────────┘ └─────┘

                    ┌──────────────────────────────┐
                    │      Credential Vault         │
                    │  (encrypted storage, refresh, │
                    │   scoping, rotation)          │
                    └──────────────────────────────┘

                    ┌──────────────────────────────┐
                    │       Event Bridge            │
                    │  (normalize, filter, route    │
                    │   external events to Core)    │
                    └──────────────────────────────┘

                    ┌──────────────────────────────┐
                    │       Entity Mapper           │
                    │  (ATLAS ID ↔ External ID      │
                    │   bidirectional mapping)      │
                    └──────────────────────────────┘
```

## 2. Component Breakdown

### 2.1 Integration Manager
**Responsibility**: Lifecycle management for all connectors and routing of integration requests.

Manages: connector registration and initialization, connection health monitoring (periodic health checks per connector), request routing (given an integration request, determine which connector handles it), graceful degradation (if a connector is unhealthy, queue requests or report unavailability), and connector configuration management.

**Public Interface**:
- `get_connector(service: str) -> Connector`
- `list_connectors() -> list[ConnectorInfo]`
- `health_check() -> dict[str, HealthStatus]`
- `register_connector(connector: Connector) -> None`
- `execute(request: IntegrationRequest) -> IntegrationResult`

### 2.2 Connector Base Class
**Responsibility**: Standard interface that all connectors implement.

Every connector provides: `connect()`, `disconnect()`, `health_check()`, `get_capabilities()` (what operations it supports), and service-specific operation methods. Connectors handle their own request/response translation, rate limiting, retry logic, and error normalization.

**Standard Interface**:
```python
class Connector(ABC):
    def connect(self, credentials: CredentialSet) -> ConnectionResult
    def disconnect(self) -> None
    def health_check(self) -> HealthStatus
    def get_capabilities(self) -> list[ConnectorCapability]
    def execute(self, operation: str, params: dict) -> OperationResult
```

### 2.3 Jira Connector
**Responsibility**: Full Jira integration respecting ATLAS user's project structure (Initiatives → Epics → Stories).

Operations: search_issues (JQL), get_issue, create_issue, update_issue, transition_issue, add_comment, get_sprint, get_board, and list_projects. Understands issue type hierarchy and can create properly structured cards. Maps Jira entities (projects, issues, users, sprints) to ATLAS entity IDs.

### 2.4 Slack Connector
**Responsibility**: Slack workspace interaction for messaging and monitoring.

Operations: list_channels, read_channel, read_thread, send_message, search_messages, get_user_info, and react_to_message. Supports both on-demand queries and continuous monitoring (channel watching for Event Bridge). Inherits patterns from the existing slack-inbox-scanner Forge plugin.

### 2.5 Google Drive Connector
**Responsibility**: Google Drive file management and content access.

Operations: search_files, get_file, create_doc, update_doc, list_folder, and share_file. Handles OAuth token management including refresh. Supports Docs, Sheets, and raw file uploads/downloads.

### 2.6 GitHub Connector
**Responsibility**: Repository operations, PR management, and CI integration.

Operations: list_repos, get_repo, create_branch, commit_files, create_pr, get_pr_status, list_issues, and get_actions_status. Critical for skill authoring workflows where new skills are committed to version control.

### 2.7 MCP Bridge
**Responsibility**: First-class integration with Model Context Protocol servers.

The MCP Bridge is distinct from other connectors because MCP servers expose tools that should be surfaced as ATLAS skills. The Bridge: discovers available MCP servers (from configuration), enumerates tools from each server, wraps each MCP tool as an ATLAS SkillDefinition (registering with Skill Engine), routes MCP tool invocations through the standard ATLAS execution pipeline, and manages MCP session lifecycle.

This is strategically important: MCP is becoming the standard for LLM-tool integration, and ATLAS should be a first-class MCP client. Additionally, ATLAS itself could expose its skills as an MCP server in Phase 3.

**Public Interface**:
- `discover_servers() -> list[MCPServerInfo]`
- `connect_server(url: str, config: MCPConfig) -> MCPSessionId`
- `list_tools(session_id: MCPSessionId) -> list[MCPTool]`
- `invoke_tool(session_id: MCPSessionId, tool: str, params: dict) -> MCPResult`
- `register_tools_as_skills(session_id: MCPSessionId) -> list[SkillId]`

### 2.8 Credential Vault
**Responsibility**: Secure credential storage and lifecycle management.

Stores all authentication credentials encrypted at rest. Supports: API keys, OAuth tokens (access + refresh), SSH keys, and service-specific tokens. Provides: credential scoping (connector X can only access credential Y), automatic OAuth token refresh, expiration tracking and alerts, and secure credential injection (connectors never see raw credentials in logs).

**Implementation**: Encrypted SQLite database. Encryption key derived from a user-provided passphrase or OS keychain. Credentials are decrypted only in memory, never written to disk in plaintext.

**Public Interface**:
- `store(service: str, credential_type: str, credential_data: dict) -> CredentialId`
- `retrieve(credential_id: CredentialId) -> CredentialSet`
- `refresh(credential_id: CredentialId) -> CredentialSet`
- `delete(credential_id: CredentialId) -> None`
- `list_credentials() -> list[CredentialInfo]` (metadata only, no secrets)

### 2.9 Event Bridge
**Responsibility**: Normalizes external service events into ATLAS observation events.

Receives events from: connector polling (periodic checks for changes), webhook ingestion (HTTP endpoint for real-time events), and MCP server notifications. Normalizes all events into the standard `ObservationEvent` format and routes them to the Agent Core via the Environment Interface's observation subscription.

**Public Interface**:
- `register_event_source(source: EventSourceConfig) -> SourceId`
- `start_polling(source_id: SourceId, interval: timedelta) -> None`
- `stop_polling(source_id: SourceId) -> None`
- `ingest_webhook(payload: dict, source: str) -> None`

### 2.10 Entity Mapper
**Responsibility**: Maintains bidirectional mappings between ATLAS internal IDs and external service IDs.

When ATLAS references "Jira ticket PROJ-123," the Entity Mapper knows the ATLAS entity ID, the Jira issue ID, the project, the last known state, and when it was last synced. This enables cross-service entity linking ("this Jira ticket is discussed in that Slack thread").

**Public Interface**:
- `map(atlas_id: str, service: str, external_id: str, metadata: dict) -> MappingId`
- `resolve_atlas(service: str, external_id: str) -> str | None`
- `resolve_external(atlas_id: str, service: str) -> str | None`
- `get_entity(atlas_id: str) -> EntityRecord`
- `list_mappings(atlas_id: str) -> list[Mapping]`

## 3. Data Models

### IntegrationRequest
- `request_id`: UUID
- `service`: string (jira, slack, gdrive, github, mcp)
- `operation`: string
- `params`: dict
- `priority`: int
- `timeout`: int
- Storage: In-memory during processing.

### ConnectorCapability
- `operation`: string
- `description`: string
- `param_schema`: JSON Schema
- `result_schema`: JSON Schema
- `requires_auth`: bool
- `risk_level`: enum (read_only, write, destructive)

### CredentialSet
- `credential_id`: UUID
- `service`: string
- `credential_type`: enum (api_key, oauth, ssh_key, token)
- `data`: dict (encrypted at rest)
- `expires_at`: datetime | None
- `refresh_token`: string | None
- `scopes`: list[string]
- `created_at`, `last_used`: datetime
- Storage: Encrypted SQLite.

### EntityRecord
- `atlas_id`: UUID
- `entity_type`: string (jira_issue, slack_message, gdrive_file, github_pr, etc.)
- `display_name`: string
- `mappings`: list[ExternalMapping]
- `last_synced`: datetime
- `cached_state`: dict (last known external state)
- Storage: SQLite.

### ExternalMapping
- `service`: string
- `external_id`: string
- `url`: string | None
- `synced_at`: datetime

## 4. Interface Contracts

### Integration Layer → Agent Core (via Event Bridge → Observation Engine)
```python
# External events arrive as standard observation events
# Routed through Environment Interface's observation system
observation_callback(event: ObservationEvent) -> None
```

### Integration Layer → Skill Engine
```python
# MCP tools registered as skills
skills.register(skill: SkillDefinition) -> SkillId

# Connector capabilities exposed as skills
skills.register(skill: SkillDefinition) -> SkillId
```

### Integration Layer → Memory System
```python
# Entity state persists in semantic memory
memory.store(entry: KnowledgeEntry) -> EntryId  # entity mappings, service state

# Connection history in episodic memory
memory.record_episode(episode: Episode) -> EpisodeId
```

### Integration Layer → Environment Interface
```python
# Network requests route through Environment
env.execute(action: NetworkAction) -> ActionResult

# Event Bridge registers with Observation Engine
env.subscribe(filter: EventFilter, callback: Callable) -> SubscriptionId
```

### Integration Layer → Control Plane
```python
# External write operations may require approval
control.check_permission(action: IntegrationAction) -> PermissionResult

# All external interactions logged
control.log_action(entry: IntegrationAuditEntry) -> None

# Credential access audited
control.log_credential_access(entry: CredentialAuditEntry) -> None
```

## 5. State Management

**Connector Lifecycle**: `disconnected → connecting → connected → degraded → disconnected`. Connectors can enter `degraded` state if health checks fail but don't fully disconnect (e.g., intermittent network issues). The Integration Manager attempts reconnection with exponential backoff.

**Credential Lifecycle**: `active → expiring → expired → refreshed → active`. OAuth tokens cycle through refresh. API keys go from active to expired when manually revoked or when expiration date passes.

**Recovery**: On restart, all connectors start in `disconnected` state. The Integration Manager reads connector configuration and credentials from storage and attempts to reconnect each. Failed reconnections are retried with backoff. The Event Bridge resumes polling after connectors are healthy.

## 6. Design Patterns

- **Plugin/Provider Pattern**: Connectors are self-contained plugins implementing a standard interface.
- **Adapter Pattern**: Each connector adapts its external service's API to ATLAS's internal request/response model.
- **Bridge Pattern**: MCP Bridge translates between MCP protocol and ATLAS skill/tool abstractions.
- **Repository Pattern**: Entity Mapper and Credential Vault follow repository patterns for storage.
- **Circuit Breaker**: Per-connector circuit breaker prevents cascading failures when services are down.
- **Event-Driven Architecture**: Event Bridge normalizes and routes external events through the existing observation pipeline.

## 7. Phased Rollout

**Phase 1 (MVP)**: Connector framework with base class and standard interface. Jira Connector (read-only: search, get issue). Slack Connector (read-only: search messages, read channels). Credential Vault with API key and OAuth token support. Entity Mapper (basic mappings). No Event Bridge (polling only, triggered by Agent Core). No MCP Bridge. No GitHub or Google Drive connectors.

**Phase 2 (Full)**: Full read-write Jira and Slack connectors. Google Drive Connector. GitHub Connector. Event Bridge with polling support. MCP Bridge with tool discovery and skill registration. Credential auto-refresh for OAuth. Cross-service entity linking.

**Phase 3 (Advanced)**: Webhook ingestion endpoint (real-time external events). ATLAS as MCP server (expose skills to other tools). Connector auto-discovery (detect available services from environment). Custom connector authoring by Skill Forge (agent writes its own connectors). Bulk synchronization for entity state.

## 8. Key Tradeoffs

**Individual connectors vs. unified API abstraction**: Chose individual connectors. A unified abstraction (e.g., wrapping everything in a generic REST client) would be simpler but loses service-specific semantics. Jira's JQL, Slack's threading model, and GitHub's PR workflow all have specific patterns that a generic wrapper would flatten. Service-specific connectors preserve these semantics.

**Polling vs. webhooks for events**: Phase 1 and 2 use polling. Webhooks require an HTTP server, which adds complexity (port management, firewall configuration, SSL). Polling is simpler and works everywhere. Webhooks added in Phase 3 as an optimization for services with high event volumes.

**Encrypted SQLite vs. OS keychain for credentials**: Chose encrypted SQLite for portability. OS keychains (macOS Keychain, Linux Secret Service) are more secure but platform-specific and harder to backup/migrate. Encrypted SQLite with OS keychain for the master key gives a good balance.

**MCP tools as first-class skills vs. passthrough**: Chose first-class skills. MCP tools are registered in the Skill Engine with full metadata, making them discoverable and composable alongside native skills. Passthrough would be simpler but would make MCP tools second-class citizens invisible to capability matching.

## 9. Open Questions

- Should ATLAS support multiple accounts per service? (e.g., personal and work Jira instances) If so, how does routing work?
- How should large data transfers be handled? (e.g., syncing an entire Google Drive folder). Streaming, chunking, or batch?
- What is the right polling interval for each service? Too frequent wastes API quota; too infrequent misses events. Should this be adaptive?
- How should connector versioning work when external APIs change? (e.g., Jira API v2 → v3)
- Should the Credential Vault support team/shared credentials, or is it strictly single-user?
