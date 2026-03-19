# Design Plan: Persistent Claude Code CLI Session Bridge

**Date:** 2026-03-19
**Status:** Draft — awaiting approval
**Branch:** `claude/clarify-agent-auth-RXArk`

---

## 1. Problem Statement

The current `ClaudeCodeBridge` calls the Anthropic Messages API directly via `AsyncAnthropic`. This gives ATLAS raw text generation but **no tool use** — Claude cannot read files, run commands, edit code, or interact with the workspace. Every call is stateless; context must be re-embedded in each prompt.

ATLAS needs Claude to **act as an agent** — reasoning over multiple turns, using tools (Read, Edit, Bash, Grep, Glob), and maintaining conversational context across a task's lifetime.

## 2. Target Architecture

Replace the direct Anthropic API calls with a bridge that drives the **Claude Code CLI** (or the `claude-agent-sdk` Python package) as a subprocess, giving Claude full tool access and persistent session context.

```
┌─────────────┐     ┌──────────────────┐     ┌────────────────┐
│ Agent Core   │────▶│ ClaudeCodeBridge  │────▶│ claude CLI      │
│ (loop, forge,│     │ (session manager) │     │ (subprocess)    │
│  cli)        │     │                   │     │ Read/Edit/Bash  │
└─────────────┘     └──────────────────┘     └────────────────┘
                           │
                     manages sessions,
                     parses JSON output,
                     tracks tokens & timing
```

## 3. Key Design Decision: SDK vs. Raw Subprocess

| Option | Pros | Cons |
|--------|------|------|
| **`claude-agent-sdk`** (Python) | Native async generators, hooks API, custom tools, session resume built-in, maintained by Anthropic | Extra dependency, abstractions may not map 1:1 to our needs |
| **Raw subprocess** (`claude -p --output-format json`) | No new dependency, full control, simpler mental model | Must handle process lifecycle, JSON parsing, error detection manually |

**Recommendation:** Use `claude-agent-sdk`. It handles the subprocess protocol, provides typed events, and supports session resume natively. If it proves too constraining, the bridge abstraction lets us swap to raw subprocess later without changing callers.

## 4. Interface Changes

### 4.1 New Contract Methods (`contracts/interfaces.py`)

Add session methods to `EnvironmentInterface` alongside the existing `claude_oneshot`:

```python
class EnvironmentInterface(ABC):
    # ... existing methods ...

    # Phase 1 (unchanged)
    async def claude_oneshot(
        self, prompt: str, system_prompt: str | None = None,
        ctx: ExecutionContext | None = None,
    ) -> ClaudeResponse: ...

    # Phase 2 (new)
    async def claude_session_start(
        self, system_prompt: str | None = None,
        allowed_tools: list[str] | None = None,
        ctx: ExecutionContext | None = None,
    ) -> str: ...  # returns session_id

    async def claude_session_send(
        self, session_id: str, message: str,
        ctx: ExecutionContext | None = None,
    ) -> ClaudeResponse: ...

    async def claude_session_close(
        self, session_id: str,
        ctx: ExecutionContext | None = None,
    ) -> None: ...
```

### 4.2 New Types (`contracts/types.py`)

```python
@dataclass
class SessionState:
    session_id: str
    status: str          # "active", "idle", "closed", "error"
    turns: int           # number of messages sent
    total_tokens: int    # cumulative token usage
    created_at: float    # monotonic timestamp
    last_active: float   # monotonic timestamp

@dataclass
class ClaudeResponse:
    content: str = ""
    parsed_output: Any = None
    tokens_used: int = 0
    execution_time_ms: int = 0
    session_id: str | None = None       # NEW — which session produced this
    tool_actions: list[dict] | None = None  # NEW — tools Claude invoked
```

### 4.3 New Error Types (`contracts/errors.py`)

```python
class SessionNotFoundError(FatalError):
    """Requested session does not exist or was already closed."""

class SessionExpiredError(RetriableError):
    """Session timed out or lost connection. Caller should create a new one."""
```

## 5. Implementation Plan

### Step 1: Add `claude-agent-sdk` dependency

- Add `claude-agent-sdk` to `pyproject.toml` dependencies
- Verify it works with Python 3.12+ and asyncio
- Confirm the `claude` CLI binary is discoverable (document requirement)

### Step 2: Implement `SessionManager` (new internal class)

File: `src/atlas/env/sessions.py`

```python
class SessionManager:
    """Manages Claude Code CLI session lifecycle."""

    def __init__(self, max_sessions: int = 3, idle_timeout: int = 300):
        self._sessions: dict[str, SessionState] = {}
        self._max_sessions = max_sessions
        self._idle_timeout = idle_timeout

    async def create(
        self, system_prompt: str | None = None,
        allowed_tools: list[str] | None = None,
    ) -> str: ...

    async def send(self, session_id: str, message: str) -> ClaudeResponse: ...

    async def close(self, session_id: str) -> None: ...

    async def close_all(self) -> None: ...

    def get_state(self, session_id: str) -> SessionState: ...

    async def _evict_idle(self) -> None:
        """Close sessions idle longer than timeout."""
        ...

    async def _wait_for_slot(self) -> None:
        """If at max capacity, wait for a session to close or evict idle."""
        ...
```

Key behaviors:
- **Pool limit**: configurable `max_sessions` (default 3), queues when full
- **Idle eviction**: sessions idle > `idle_timeout` seconds are auto-closed
- **Session resume**: uses `--resume <session_id>` for multi-turn context
- **Error mapping**: subprocess failures → `ClaudeCodeError` / `SessionExpiredError`
- **Token tracking**: accumulates `tokens_used` across turns per session

### Step 3: Refactor `ClaudeCodeBridge`

File: `src/atlas/env/claude.py`

The bridge gains a `SessionManager` but preserves the existing `oneshot()` method for backward compatibility.

```python
class ClaudeCodeBridge:
    def __init__(self, config: ClaudeConfig):
        self._config = config
        self._sessions = SessionManager(
            max_sessions=config.max_sessions,
            idle_timeout=config.idle_timeout,
        )

    # Existing — now implemented via `claude -p` (one-shot CLI mode)
    async def oneshot(self, prompt: str, system_prompt: str | None = None) -> ClaudeResponse: ...

    # New — session lifecycle
    async def create_session(self, system_prompt: str | None = None,
                              allowed_tools: list[str] | None = None) -> str: ...
    async def send_message(self, session_id: str, message: str) -> ClaudeResponse: ...
    async def close_session(self, session_id: str) -> None: ...
    async def close_all_sessions(self) -> None: ...
    def get_session_state(self, session_id: str) -> SessionState: ...
```

**Migration of `oneshot()`**: The existing `oneshot()` switches from direct Anthropic SDK to `claude -p --output-format json`. This gives one-shot calls tool access too, which is a significant upgrade. The response JSON is parsed into the existing `ClaudeResponse` type.

### Step 4: Update `EnvironmentFacade`

Route the new session methods through to the bridge, propagating `ExecutionContext` for correlation ID tracing.

### Step 5: Update Configuration

File: `src/atlas/config.py` and `config/default.yaml`

```python
@dataclass
class ClaudeConfig:
    api_key: str = ""
    model: str = "claude-sonnet-4-20250514"
    timeout_seconds: int = 120
    max_sessions: int = 3
    idle_timeout: int = 300           # seconds
    allowed_tools: list[str] = field(
        default_factory=lambda: ["Read", "Glob", "Grep", "Bash", "Edit", "Write"]
    )
```

### Step 6: Update Callers (incremental)

Existing callers (`loop.py`, `forge.py`, `cli.py`) continue using `claude_oneshot()` — no changes required for backward compatibility. New session-based callers can opt in:

**Future caller pattern (execution loop using sessions):**
```python
session_id = await self._env.claude_session_start(
    system_prompt=PLANNING_SYSTEM_PROMPT,
    allowed_tools=["Read", "Grep", "Glob", "Bash"],
)
try:
    response = await self._env.claude_session_send(session_id, task_prompt)
    # Claude can now read files, run tests, etc. within this turn
finally:
    await self._env.claude_session_close(session_id)
```

### Step 7: Testing

- **Unit tests** for `SessionManager`: creation, send, close, idle eviction, pool limits
- **Unit tests** for refactored `ClaudeCodeBridge`: oneshot via CLI, session lifecycle
- **Mock boundary**: Mock at `claude-agent-sdk`'s `query()` function — same principle as current mock boundary but one layer up
- **Integration test**: End-to-end session that creates → sends 3 messages → closes, with a mock CLI returning canned JSON

## 6. Files Changed

| File | Change |
|------|--------|
| `pyproject.toml` | Add `claude-agent-sdk` dependency |
| `src/atlas/contracts/interfaces.py` | Add session methods to `EnvironmentInterface` |
| `src/atlas/contracts/types.py` | Add `SessionState`, extend `ClaudeResponse` |
| `src/atlas/contracts/errors.py` | Add `SessionNotFoundError`, `SessionExpiredError` |
| `src/atlas/config.py` | Add `ClaudeConfig` dataclass |
| `config/default.yaml` | Add `claude:` config section |
| `src/atlas/env/sessions.py` | **New** — `SessionManager` class |
| `src/atlas/env/claude.py` | Refactor to use CLI subprocess + add session methods |
| `src/atlas/env/facade.py` | Route new session methods |
| `src/atlas/cli.py` | Wire `ClaudeConfig` into bridge construction |
| `tests/unit/env/test_sessions.py` | **New** — SessionManager tests |
| `tests/unit/env/test_claude.py` | Update for CLI-based bridge |
| `tests/integration/test_session_flow.py` | **New** — end-to-end session test |

## 7. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| `claude-agent-sdk` API changes | Pin version; bridge abstraction isolates callers |
| CLI subprocess hangs | `timeout` on all subprocess calls; `idle_timeout` eviction |
| Session context grows stale | Caller controls session lifetime; sessions are cheap to recreate |
| Rate limits with multiple sessions | `max_sessions` pool cap; queue when full |
| Claude CLI not installed | Fail-fast at `ClaudeCodeBridge.__init__` with clear error |
| Token budget blowup in long sessions | Track cumulative tokens per session; callers can check `SessionState.total_tokens` |

## 8. What This Does NOT Cover

- **Streaming responses** — deferred; batch JSON is sufficient for Phase 2
- **Custom MCP tools** — can be added later via SDK's custom tools API
- **Multi-agent** — Phase 3 concern; sessions are single-agent
- **Reactive mode triggers** — sessions don't auto-start from file watchers (yet)
- **Migration of existing callers to sessions** — callers opt in incrementally; `oneshot()` remains the default path

## 9. Implementation Order

1. Config + types + errors (foundation, no behavior change)
2. `SessionManager` + tests (core new logic, isolated)
3. `ClaudeCodeBridge` refactor + tests (switches from API SDK to CLI)
4. `EnvironmentFacade` + contract updates (wiring)
5. CLI wiring (config passthrough)
6. Integration test (end-to-end validation)
