# Domain 4: Environment Interface — Architectural Design Plan

## 1. Architecture Overview

The Environment Interface is ATLAS's sensory and motor system. It provides a unified abstraction over everything the agent can see and do in the world: reading files, running commands, watching for changes, and interacting with the desktop. Every interaction with the outside world passes through this layer, making it the single enforcement point for safety, logging, and resource management.

The architecture follows a **provider model**: each category of environment capability (filesystem, process, network, desktop) is implemented as a pluggable provider behind a unified `Environment` facade. An **Observation Engine** runs in parallel, passively monitoring configured sources and emitting structured events.

```
                    ┌──────────────────────────────┐
                    │       Environment Facade      │
                    │  (unified action/query API)   │
                    └──────────────┬───────────────┘
                                   │
          ┌─────────┬──────────────┼──────────────┬─────────┐
          │         │              │              │         │
   ┌──────▼───┐ ┌───▼─────┐ ┌─────▼────┐ ┌──────▼───┐ ┌───▼──────┐
   │Filesystem│ │ Process  │ │ Network  │ │ Desktop  │ │ Claude   │
   │ Provider │ │ Provider │ │ Provider │ │ Provider │ │ Code     │
   │          │ │          │ │          │ │          │ │ Bridge   │
   └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘

                    ┌──────────────────────────────┐
                    │     Observation Engine        │
                    │  (watchers, triggers,         │
                    │   debouncing, event emission) │
                    └──────────────────────────────┘

                    ┌──────────────────────────────┐
                    │    Environment State Model    │
                    │  (snapshot of current state   │
                    │   for injection into prompts) │
                    └──────────────────────────────┘
```

## 2. Component Breakdown

### 2.1 Environment Facade
**Responsibility**: Single entry point for all environment interactions, routing to appropriate providers.

The Facade accepts `EnvironmentAction` objects, validates them, routes them to the correct provider, and returns structured results. It also enforces cross-cutting concerns: every action passes through Control Plane permission checks and audit logging before execution.

**Public Interface**:
- `execute(action: EnvironmentAction) -> ActionResult`
- `execute_async(action: EnvironmentAction) -> Future[ActionResult]`
- `get_state() -> EnvironmentState`
- `get_capabilities() -> list[Capability]`

### 2.2 Filesystem Provider
**Responsibility**: All file and directory operations.

Supports: read_file, write_file, create_directory, delete, copy, move, list_directory, search (glob/regex), file_info (size, dates, permissions), and watch (delegate to Observation Engine). Enforces path boundaries from Control Plane configuration: which directories are readable, which are writable, which are off-limits.

**Public Interface**:
- `read(path: str) -> FileContent`
- `write(path: str, content: str | bytes, mode: str) -> WriteResult`
- `list_dir(path: str, recursive: bool, pattern: str) -> list[FileInfo]`
- `search(root: str, pattern: str, content_match: str) -> list[FileInfo]`
- `watch(path: str, events: list[str]) -> WatcherId`
- `get_workspace() -> WorkspaceInfo`

### 2.3 Process Provider
**Responsibility**: Spawning, monitoring, and managing external processes.

Supports: execute_command (run and wait), start_process (run in background), kill_process, get_process_status, and list_processes. Manages a process table tracking all child processes. Handles zombie process cleanup and orphan detection on daemon restart.

**Public Interface**:
- `execute(cmd: str, cwd: str, env: dict, timeout: int) -> CommandResult`
- `start(cmd: str, cwd: str, env: dict) -> ProcessHandle`
- `kill(pid: int, signal: int) -> None`
- `list_managed() -> list[ProcessInfo]`
- `wait(pid: int, timeout: int) -> ProcessResult`

### 2.4 Network Provider
**Responsibility**: HTTP requests and network connectivity management.

Supports: http_request (GET, POST, PUT, DELETE), websocket_connect, check_connectivity, and dns_resolve. Enforces network boundaries from Control Plane: allowed hosts, blocked hosts, rate limits per host.

**Public Interface**:
- `http(method: str, url: str, headers: dict, body: Any, timeout: int) -> HttpResponse`
- `check_connectivity(host: str) -> ConnectivityResult`

### 2.5 Desktop Provider
**Responsibility**: Desktop-level interactions beyond files and processes.

Supports: system_notifications (send desktop notifications), clipboard (read/write), and system_info (OS version, CPU, memory, disk). Designed for extensibility; future additions might include window management, screen capture, or keyboard simulation.

**Public Interface**:
- `notify(title: str, body: str, urgency: str) -> None`
- `clipboard_read() -> str`
- `clipboard_write(content: str) -> None`
- `system_info() -> SystemInfo`

### 2.6 Claude Code Bridge
**Responsibility**: Manages all interactions with the Claude Code CLI, the most critical external process.

This is a specialized process manager for Claude Code that handles: session lifecycle (starting interactive sessions, detecting timeouts, reconnecting), prompt construction (assembling system prompts, memory context, and task instructions), response parsing (extracting structured output from Claude's responses), rate limit detection and backoff, and context window management (tracking how much context has been consumed in a session).

The Bridge supports two modes: **one-shot** (`claude -p "prompt"` for independent calls) and **session** (interactive mode for multi-turn reasoning). The Agent Core specifies which mode to use per call.

**Public Interface**:
- `one_shot(prompt: str, system_prompt: str) -> ClaudeResponse`
- `create_session(system_prompt: str) -> SessionId`
- `send_message(session_id: SessionId, message: str) -> ClaudeResponse`
- `close_session(session_id: SessionId) -> None`
- `get_session_state(session_id: SessionId) -> SessionState`
- `get_health() -> ClaudeCodeHealth`

**Internal Structure**: Maintains a pool of sessions (configurable max). Monitors each session's token usage. Auto-closes idle sessions. Queues requests when all sessions are busy.

### 2.7 Observation Engine
**Responsibility**: Passive monitoring that generates structured events for the Agent Core's reactive processing.

Manages a set of **Watchers**, each monitoring a specific source: `FileWatcher` (inotify/FSEvents for filesystem changes), `CronWatcher` (time-based triggers), `ProcessWatcher` (monitors managed processes for state changes), and `CustomWatcher` (extensible for new event sources).

Events are debounced (rapid file changes don't flood the system), filtered (configurable rules for what's interesting), and emitted as `ObservationEvent` objects to registered subscribers.

**Public Interface**:
- `register_watcher(config: WatcherConfig) -> WatcherId`
- `unregister_watcher(watcher_id: WatcherId) -> None`
- `subscribe(filter: EventFilter, callback: Callable) -> SubscriptionId`
- `unsubscribe(subscription_id: SubscriptionId) -> None`
- `list_watchers() -> list[WatcherInfo]`

### 2.8 Environment State Model
**Responsibility**: Produces a structured snapshot of the current environment for prompt injection.

Assembles data from all providers into a coherent state object: workspace directory structure, running processes, system resource availability, network connectivity, active Claude Code sessions, and recent observation events. The snapshot is designed to be token-efficient (summarized, not raw dumps).

**Public Interface**:
- `snapshot() -> EnvironmentState`
- `snapshot_section(section: str) -> str` (just filesystem, just processes, etc.)

## 3. Data Models

### EnvironmentAction
- `action_id`: UUID
- `action_type`: enum (filesystem_read, filesystem_write, process_execute, process_start, network_http, desktop_notify, claude_code_oneshot, claude_code_session_send)
- `provider`: string
- `params`: dict (action-type-specific)
- `timeout`: int (seconds)
- `requires_approval`: bool (set by Control Plane check)
- Storage: In-memory; logged to audit.

### ActionResult
- `action_id`: UUID
- `status`: enum (success, failure, timeout, denied)
- `output`: Any (action-type-specific)
- `error`: string | None
- `execution_time_ms`: int
- `side_effects`: list[SideEffect] (files modified, processes started, etc.)
- Storage: In-memory; summary logged.

### ObservationEvent
- `event_id`: UUID
- `source`: string (watcher ID)
- `event_type`: string (file_created, file_modified, cron_fired, process_exited, etc.)
- `details`: dict
- `timestamp`: datetime
- Storage: In-memory queue; significant events written to episodic memory by Agent Core.

### EnvironmentState
- `timestamp`: datetime
- `workspace`: WorkspaceSnapshot (directory tree summary)
- `processes`: list[ProcessInfo]
- `system`: SystemInfo (CPU, memory, disk)
- `network`: NetworkStatus
- `claude_code`: ClaudeCodeHealth
- `recent_observations`: list[ObservationEvent] (last N events)
- Storage: Regenerated on demand, not persisted.

### ClaudeResponse
- `response_id`: UUID
- `session_id`: SessionId | None
- `content`: string (raw response text)
- `parsed_output`: Any | None (if structured output was requested)
- `tokens_used`: int (estimated)
- `execution_time_ms`: int

## 4. Interface Contracts

### Environment Interface → Agent Core
```python
# Action execution (async)
env.execute(action: EnvironmentAction) -> ActionResult

# State queries (synchronous, fast)
env.get_state() -> EnvironmentState

# Observation subscription (event-driven)
env.subscribe(filter: EventFilter, callback: Callable) -> SubscriptionId
```

### Environment Interface → Skill Engine
```python
# Skills use environment through the same facade
env.execute(action: EnvironmentAction) -> ActionResult

# Sandbox for skill testing
env.create_sandbox(config: SandboxConfig) -> SandboxId
env.execute_in_sandbox(sandbox_id: SandboxId, action: EnvironmentAction) -> ActionResult
env.destroy_sandbox(sandbox_id: SandboxId) -> None
```

### Environment Interface → Control Plane
```python
# Every action is checked (synchronous, must be fast)
control.check_permission(action: EnvironmentAction) -> PermissionResult

# Every action is logged (async)
control.log_action(entry: ActionAuditEntry) -> None
```

### Environment Interface → Memory System
```python
# Claude Code Bridge reads context for prompt construction
memory.retrieve_context(query: ContextQuery) -> ContextBundle
memory.get_working_context() -> WorkingContext
```

## 5. State Management

**Provider State**: Each provider maintains minimal internal state (open file handles, running processes, active sessions). Provider state is reconstructible: on restart, the filesystem provider re-scans the workspace, the process provider checks for orphan processes, and the Claude Code Bridge creates fresh sessions.

**Observation Engine State**: Watcher registrations persist in a config file. On restart, all watchers are re-initialized from config. Events generated during downtime are missed (not queued), which is acceptable because the file watcher will report current state, not historical changes.

**Claude Code Session State**: Sessions are ephemeral. On daemon restart, all sessions are assumed dead and recreated as needed. The Agent Core is responsible for reconstructing session context from Memory System.

## 6. Design Patterns

- **Facade Pattern**: Unified `Environment` interface hides provider complexity from consumers.
- **Provider/Plugin Pattern**: Each environment capability is a pluggable provider implementing a standard interface.
- **Observer Pattern**: Observation Engine uses publish-subscribe for event distribution.
- **Bridge Pattern**: Claude Code Bridge abstracts the specific CLI implementation details from the rest of the system.
- **Proxy Pattern**: Every action goes through a Control Plane proxy for permission checks.
- **Object Pool**: Claude Code session pool manages reusable sessions.

## 7. Phased Rollout

**Phase 1 (MVP)**: Filesystem Provider (read, write, list, search). Process Provider (execute command, basic process tracking). Claude Code Bridge (one-shot mode only). Environment State Model (filesystem and process sections). No Observation Engine. No Network Provider (external calls go through Integration Layer). No Desktop Provider. No sandboxing.

**Phase 2 (Full)**: Observation Engine with FileWatcher and CronWatcher. Claude Code Bridge session mode. Network Provider. Desktop Provider (notifications). Sandbox support for Skill Engine testing. Full environment state model. Path boundary enforcement from Control Plane.

**Phase 3 (Advanced)**: Advanced Claude Code session management (session pool, context migration between sessions). Browser automation provider (headless browser for web interaction). Screen capture and OCR provider (see what's on screen). Process dependency tracking (understand which processes depend on each other). Predictive resource management (pre-allocate resources for anticipated tasks).

## 8. Key Tradeoffs

**Unified facade vs. direct provider access**: Chose facade. Forces all actions through a single enforcement point (permissions, logging, resource tracking). Slightly more indirection but dramatically simpler security model. Skills and Agent Core never bypass safety checks.

**Claude Code one-shot vs. session default**: Phase 1 starts with one-shot only. Sessions are more powerful (multi-turn reasoning, persistent context) but harder to manage (timeouts, stale context, connection failures). One-shot is simple, stateless, and reliable. Sessions added in Phase 2 after the one-shot path is proven.

**Polling vs. event-driven observation**: Chose event-driven (inotify/FSEvents) for filesystem, with polling fallback for platforms that don't support efficient file watching. Event-driven is dramatically more efficient for typical desktop workloads.

**Embedded sandbox vs. container-based**: Chose embedded (directory isolation + restricted permissions). Container-based (Docker) would provide stronger isolation but adds a heavy dependency and startup overhead. For skill testing, directory-level isolation is sufficient; the Control Plane provides additional safety boundaries.

## 9. Open Questions

- How should the Claude Code Bridge handle the distinction between Claude Code CLI modes (interactive vs. one-shot vs. pipe)? The CLI's interface may evolve; the bridge needs to be adaptable.
- What is the right session pool size for Claude Code? Too few creates a bottleneck; too many wastes resources and may hit rate limits.
- Should the Observation Engine support external webhook ingestion (HTTP endpoint that receives webhooks from services like GitHub)? This blurs the line with Integration Layer.
- How should file content be summarized for the environment state model? Large directories need intelligent summarization, not raw listings.
- What is the right approach for cross-platform compatibility (macOS vs. Linux)? Provider implementations may differ significantly for desktop interactions and file watching.
