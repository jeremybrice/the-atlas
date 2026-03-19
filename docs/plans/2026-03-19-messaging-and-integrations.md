# Design Plan: Messaging Adapters & Integration Framework

**Date:** 2026-03-19
**Status:** Draft — awaiting approval
**Branch:** `claude/clarify-agent-auth-RXArk`
**Depends on:** Session Bridge plan (for Claude tool-use in goal execution)

---

## 1. Problem Statement

ATLAS has the daemon, reactive engine, webhook server, and connector framework — but no way to **talk to the agent from a phone**. The Reddit post makes clear that OpenClaw's killer feature isn't autonomy, it's **messaging as UI**: send a Telegram message, get a structured response back. ATLAS also lacks a generic HTTP skill for calling arbitrary APIs (Whoop, Composio, etc.) and has no token cost tracking.

This plan closes three gaps:
1. **Messaging adapters** — bidirectional Telegram (and later Slack/Discord) channels
2. **HTTP/REST skill** — a seed skill for calling arbitrary APIs with auth headers
3. **Token budget tracking** — cumulative spend tracking with alerts

---

## 2. Architecture Overview

```
┌──────────┐   ┌──────────┐   ┌──────────┐
│ Telegram │   │  Slack   │   │ Discord  │
│  Bot API │   │ Events   │   │ Gateway  │
└────┬─────┘   └────┬─────┘   └────┬─────┘
     │              │              │
     ▼              ▼              ▼
┌────────────────────────────────────────┐
│         MessagingAdapter (ABC)         │
│  receive() → goal   |   send() → reply│
└────────────────┬───────────────────────┘
                 │
    ┌────────────▼────────────┐
    │    ObservationEngine    │
    │  on_event(MESSAGING)    │
    │         │               │
    │    EventRouter.match()  │
    │         │               │
    │  goal_executor(goal)    │
    │         │               │
    │    response → adapter   │
    └─────────────────────────┘
```

The messaging adapter is **not a connector** (ConnectorABC). Connectors are for services ATLAS calls out to. Messaging adapters are **channels** — they maintain a long-lived connection (polling or websocket), receive inbound messages, dispatch them as goals, and relay results back. They sit alongside the daemon loop, not inside the webhook pipeline.

---

## 3. Detailed Design

### 3.1 Messaging Adapter Interface

File: `src/atlas/messaging/adapter.py`

```python
class MessagingAdapter(ABC):
    """Bidirectional messaging channel."""

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """e.g., 'telegram', 'slack', 'discord'"""

    @abstractmethod
    async def start(self) -> None:
        """Begin listening for inbound messages."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully disconnect."""

    @abstractmethod
    async def send(self, chat_id: str, text: str, **kwargs) -> None:
        """Send a message back to a specific chat/channel."""

    @abstractmethod
    async def send_typing(self, chat_id: str) -> None:
        """Show typing indicator while processing."""
```

The adapter doesn't handle goal execution itself. It:
1. Receives a message
2. Creates an `ObservationEvent(event_type=MESSAGING, source="telegram", payload={chat_id, text, user_id})`
3. Calls `on_message_callback(event, reply_func)` where `reply_func` is a bound `self.send(chat_id, ...)`
4. The daemon's message handler executes the goal and calls `reply_func` with the result

### 3.2 New EventType

Add to `contracts/types.py`:

```python
class EventType(str, Enum):
    FILESYSTEM = "filesystem"
    SCHEDULED = "scheduled"
    GOAL = "goal"
    WEBHOOK = "webhook"
    MESSAGING = "messaging"    # NEW
```

### 3.3 Telegram Adapter

File: `src/atlas/messaging/telegram.py`

Uses the `python-telegram-bot` library (async, well-maintained, 25k+ stars).

```python
class TelegramAdapter(MessagingAdapter):
    def __init__(
        self,
        bot_token: str,
        allowed_user_ids: list[int],   # CRITICAL: whitelist only
        goal_handler: GoalHandler,
        max_message_length: int = 4096,
    ):
        self._bot_token = bot_token
        self._allowed_users = set(allowed_user_ids)
        self._goal_handler = goal_handler
        self._app: Application | None = None

    @property
    def channel_name(self) -> str:
        return "telegram"

    async def start(self) -> None:
        self._app = ApplicationBuilder().token(self._bot_token).build()
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
        self._app.add_handler(CommandHandler("status", self._handle_status))
        self._app.add_handler(CommandHandler("pause", self._handle_pause))
        self._app.add_handler(CommandHandler("resume", self._handle_resume))
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def send(self, chat_id: str, text: str, **kwargs) -> None:
        # Split long messages at 4096 char boundary
        for chunk in self._split_message(text):
            await self._app.bot.send_message(
                chat_id=int(chat_id),
                text=chunk,
                parse_mode="Markdown",
            )

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if user_id not in self._allowed_users:
            await update.message.reply_text("Unauthorized.")
            return

        chat_id = str(update.effective_chat.id)
        text = update.message.text

        # Show typing while processing
        await self.send_typing(chat_id)

        # Execute goal and reply
        try:
            result = await self._goal_handler(text)
            await self.send(chat_id, result)
        except Exception as e:
            await self.send(chat_id, f"Error: {e}")
```

**Security model:**
- `allowed_user_ids` is a **mandatory whitelist**. No message from an unknown user is processed — period.
- Bot token is loaded from vault or config, never hardcoded.
- Messages are not logged to episodic memory by default (opt-in via config flag) to avoid leaking personal data.

**Telegram commands:**
- Any text message → treated as a goal, executed via `goal_handler`
- `/status` → daemon status (uptime, active task, pause state)
- `/pause` → emergency pause
- `/resume` → resume execution

### 3.4 Goal Handler (Daemon Integration)

The daemon loop gains a `MessageGoalHandler` that bridges messaging adapters to the execution loop:

File: `src/atlas/daemon/message_handler.py`

```python
class MessageGoalHandler:
    """Bridges messaging adapters to the execution loop."""

    def __init__(
        self,
        goal_executor: Callable,
        memory: MemoryInterface,
        token_tracker: TokenTracker,
    ):
        self._goal_executor = goal_executor
        self._memory = memory
        self._token_tracker = token_tracker
        self._active_goals: dict[str, asyncio.Task] = {}

    async def handle(self, goal_text: str, chat_id: str | None = None) -> str:
        """Execute a goal and return the text result."""
        # Check token budget before starting
        if self._token_tracker.is_over_budget():
            return (
                f"Daily token budget exhausted "
                f"(${self._token_tracker.today_spend:.2f} / "
                f"${self._token_tracker.daily_budget:.2f}). "
                f"Resuming tomorrow."
            )

        result = await self._goal_executor(goal_text)
        return self._format_result(result)

    def _format_result(self, result: dict) -> str:
        """Format execution result for messaging (concise, markdown-friendly)."""
        status = result.get("status", "unknown")
        summary = result.get("summary", "")
        tasks_completed = result.get("tasks_completed", 0)
        tasks_total = result.get("tasks_total", 0)

        lines = [f"**{status.upper()}** — {summary}"]
        if tasks_total > 0:
            lines.append(f"Tasks: {tasks_completed}/{tasks_total}")
        if errors := result.get("errors"):
            lines.append(f"Errors: {errors[-1]}")
        return "\n".join(lines)
```

### 3.5 Daemon Loop Changes

File: `src/atlas/daemon/loop.py`

```python
class DaemonLoop:
    def __init__(self, ..., messaging_adapters: list[MessagingAdapter] | None = None):
        self._messaging_adapters = messaging_adapters or []

    async def start(self):
        # ... existing socket + http startup ...

        # Start messaging adapters
        for adapter in self._messaging_adapters:
            await adapter.start()
            logger.info(f"Messaging adapter started: {adapter.channel_name}")

    async def shutdown(self):
        # Stop messaging adapters
        for adapter in self._messaging_adapters:
            await adapter.stop()
        # ... existing shutdown ...
```

### 3.6 Configuration

Add to `src/atlas/config.py`:

```python
@dataclass
class TelegramConfig:
    enabled: bool = False
    bot_token: str = ""                  # or vault reference
    allowed_user_ids: list[int] = field(default_factory=list)
    log_messages: bool = False           # opt-in episodic memory logging

@dataclass
class MessagingConfig:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    # Future: slack, discord

@dataclass
class TokenBudgetConfig:
    enabled: bool = False
    daily_budget_usd: float = 5.0
    alert_threshold_pct: float = 80.0    # alert at 80% of daily budget
    model_costs: dict[str, float] = field(default_factory=lambda: {
        "claude-haiku-4-5-20251001": 0.001,     # per 1k tokens (approx)
        "claude-sonnet-4-6": 0.003,
        "claude-opus-4-6": 0.015,
    })

@dataclass
class AtlasConfig:
    # ... existing fields ...
    messaging: MessagingConfig = field(default_factory=MessagingConfig)
    token_budget: TokenBudgetConfig = field(default_factory=TokenBudgetConfig)
```

Config YAML:
```yaml
messaging:
  telegram:
    enabled: true
    bot_token: "${ATLAS_TELEGRAM_TOKEN}"  # env var or vault
    allowed_user_ids: [123456789]
    log_messages: false

token_budget:
  enabled: true
  daily_budget_usd: 5.00
  alert_threshold_pct: 80
```

---

## 4. HTTP/REST Seed Skill

The Reddit user's Whoop, Composio, and AgentMail integrations all boil down to one thing: **calling an HTTP API with auth headers and parsing the JSON response**. Rather than building bespoke connectors for each, we add a general-purpose `http.request` seed skill.

File: `src/atlas/skills/seeds/http_request.py`

```python
SKILL_ID = "http.request"
SKILL_NAME = "HTTP Request"
SKILL_DESCRIPTION = "Make HTTP requests to external APIs with configurable auth"
SKILL_RISK = "medium"  # network access = medium risk

async def handler(params: dict) -> dict:
    """
    params:
        url: str (required)
        method: str = "GET"
        headers: dict = {}
        body: dict | str | None = None
        auth_type: str | None = None        # "bearer", "basic", "api_key"
        auth_value: str | None = None       # token, "user:pass", key value
        auth_header: str = "Authorization"  # for api_key type
        timeout: int = 30
        extract_json: bool = True           # parse response as JSON

    returns:
        status_code: int
        headers: dict
        body: str | dict
        elapsed_ms: int
    """
```

**Security considerations:**
- Risk level `medium` → requires approval under default policy unless a standing rule allows it
- `auth_value` should come from the vault, not hardcoded in task params
- URL allowlisting can be enforced via policy engine blocked_paths (extend to URLs)
- No following redirects to localhost/internal IPs (SSRF protection)

**What this unlocks:**
- Whoop API (sleep data pull)
- Composio OAuth token exchange + API calls
- AgentMail polling
- Any REST API — no custom connector needed per service

---

## 5. Token Budget Tracking

File: `src/atlas/control/token_tracker.py`

```python
@dataclass
class TokenUsageRecord:
    timestamp: datetime
    model: str
    tokens_in: int
    tokens_out: int
    estimated_cost_usd: float
    mission_id: str | None = None
    source: str = ""  # "goal", "cron", "forge", "oneshot"

class TokenTracker:
    """Tracks cumulative token usage and enforces daily budgets."""

    def __init__(self, db: DatabaseStore, config: TokenBudgetConfig):
        self._db = db
        self._config = config

    async def record(self, record: TokenUsageRecord) -> None:
        """Record token usage. Alert if approaching budget."""

    @property
    async def today_spend(self) -> float:
        """Total USD spent today."""

    def is_over_budget(self) -> bool:
        """Check if daily budget is exhausted."""

    async def get_daily_summary(self) -> dict:
        """Breakdown by model, source, mission."""

    async def get_weekly_summary(self) -> dict:
        """7-day trend for the cron audit use case."""
```

Integration points:
- `ClaudeCodeBridge.oneshot()` → records tokens after each call
- `MessageGoalHandler` → checks budget before execution
- Scheduled trigger → daily cost summary via messaging adapter
- Dashboard API → `GET /api/token/usage` endpoint

---

## 6. Scheduled Briefings (Cron-to-Chat Pattern)

The Reddit user's morning briefings, email summaries, and calendar reminders are all the same pattern: **scheduled trigger → goal execution → message to chat**. ATLAS already has `ScheduledTrigger` — we need to wire its output to a messaging adapter instead of just logging it.

Current flow:
```
ScheduledTrigger → ObservationEvent → EventRouter → goal_executor → (result discarded)
```

New flow:
```
ScheduledTrigger → ObservationEvent → EventRouter → goal_executor → MessageGoalHandler → TelegramAdapter.send()
```

This requires the reactive rule to specify a **reply channel**:

```yaml
reactive:
  enabled: true
  rules:
    - name: "morning-briefing"
      trigger:
        type: "scheduled"
        pattern: "schedule:morning-briefing"
      goal: "Check my calendar for today, summarize any morning meetings, and get the weather for [city]"
      reply_to:
        channel: "telegram"
        chat_id: "123456789"
      cooldown_seconds: 86400

    - name: "email-digest"
      trigger:
        type: "scheduled"
        pattern: "schedule:email-digest"
      goal: "Summarize my emails from the last 24 hours, flag anything urgent"
      reply_to:
        channel: "telegram"
        chat_id: "123456789"
      cooldown_seconds: 43200
```

This means extending `ReactiveRule` in `contracts/types.py`:

```python
@dataclass
class ReplyTarget:
    channel: str       # "telegram", "slack"
    chat_id: str       # channel/user ID

@dataclass
class ReactiveRule:
    # ... existing fields ...
    reply_to: ReplyTarget | None = None  # NEW — where to send the result
```

And the observation engine's goal dispatch becomes:
```python
async def _dispatch_goal(self, goal_text: str, reply_to: ReplyTarget | None = None):
    result = await self._goal_handler(goal_text)
    if reply_to and reply_to.channel in self._messaging_adapters:
        adapter = self._messaging_adapters[reply_to.channel]
        await adapter.send(reply_to.chat_id, self._format_result(result))
```

---

## 7. Model Routing

The Reddit user runs Haiku for cheap crons, Sonnet for chat, Opus for hard stuff. ATLAS currently has a single model in config. Add per-context model selection:

File: extend `src/atlas/config.py`

```python
@dataclass
class ModelRoutingConfig:
    default: str = "claude-sonnet-4-6"
    cron: str = "claude-haiku-4-5-20251001"     # scheduled triggers
    interactive: str = "claude-sonnet-4-6"       # messaging/CLI goals
    planning: str = "claude-sonnet-4-6"          # mission planning
    forge: str = "claude-sonnet-4-6"             # skill generation
```

The `ClaudeCodeBridge` gains a `model` parameter on `oneshot()`:
```python
async def oneshot(self, prompt: str, system_prompt: str | None = None,
                  model: str | None = None) -> ClaudeResponse:
    model = model or self._config.model_routing.default
    ...
```

Callers tag their context:
- `ScheduledTrigger` goals → `model_routing.cron`
- `MessageGoalHandler` → `model_routing.interactive`
- `ExecutionLoop._plan()` → `model_routing.planning`
- `SkillForge.create_skill()` → `model_routing.forge`

---

## 8. Implementation Phases

### Phase A: Foundation (no new dependencies)

| Step | Files | What |
|------|-------|------|
| A1 | `contracts/types.py` | Add `EventType.MESSAGING`, `ReplyTarget`, extend `ReactiveRule` |
| A2 | `config.py`, `default.yaml` | Add `MessagingConfig`, `TokenBudgetConfig`, `ModelRoutingConfig` |
| A3 | `control/token_tracker.py` (new) | Token usage recording + budget checks |
| A4 | `skills/seeds/http_request.py` (new) | HTTP/REST seed skill |
| A5 | `skills/registry.py` | Register `http.request` as 5th seed skill |
| A6 | Tests for A3, A4 | Unit tests for token tracker and HTTP skill |

### Phase B: Messaging Core

| Step | Files | What |
|------|-------|------|
| B1 | `messaging/__init__.py`, `messaging/adapter.py` (new) | MessagingAdapter ABC |
| B2 | `messaging/telegram.py` (new) | TelegramAdapter implementation |
| B3 | `daemon/message_handler.py` (new) | MessageGoalHandler (goal → formatted reply) |
| B4 | `daemon/loop.py` | Wire adapters into daemon lifecycle |
| B5 | `observation/engine.py` | Support `reply_to` on reactive rules |
| B6 | `cli.py` | Wire TelegramConfig → adapter construction in daemon startup |
| B7 | Tests for B2, B3 | Mock telegram bot, test message flow |

### Phase C: Integration Wiring

| Step | Files | What |
|------|-------|------|
| C1 | `env/claude.py` | Add `model` param to oneshot, integrate token tracking |
| C2 | `core/loop.py` | Pass model context to bridge calls |
| C3 | `integrations/dashboard.py` | Add `/api/token/usage` endpoint |
| C4 | `observation/engine.py` | Wire messaging adapters for cron reply routing |
| C5 | Integration test | End-to-end: scheduled trigger → goal → telegram reply |

### Phase D: Polish & Extend (optional, incremental)

| Step | What |
|------|------|
| D1 | Slack adapter (same ABC, different transport) |
| D2 | Discord adapter |
| D3 | Composio OAuth connector (generic OAuth2 flow) |
| D4 | Voice memo ingestion skill (whisper transcription) |
| D5 | Vault integration for `http.request` auth values |

---

## 9. Files Changed/Created

| File | Change |
|------|--------|
| `pyproject.toml` | Add `python-telegram-bot`, `httpx` dependencies |
| `src/atlas/contracts/types.py` | `EventType.MESSAGING`, `ReplyTarget`, extend `ReactiveRule` |
| `src/atlas/config.py` | `MessagingConfig`, `TokenBudgetConfig`, `ModelRoutingConfig` |
| `config/default.yaml` | New config sections |
| `src/atlas/messaging/__init__.py` | **New** — package init |
| `src/atlas/messaging/adapter.py` | **New** — MessagingAdapter ABC |
| `src/atlas/messaging/telegram.py` | **New** — TelegramAdapter |
| `src/atlas/daemon/message_handler.py` | **New** — MessageGoalHandler |
| `src/atlas/daemon/loop.py` | Wire messaging adapters into lifecycle |
| `src/atlas/control/token_tracker.py` | **New** — TokenTracker |
| `src/atlas/skills/seeds/http_request.py` | **New** — HTTP/REST seed skill |
| `src/atlas/skills/registry.py` | Register http.request |
| `src/atlas/env/claude.py` | Add model param, token recording |
| `src/atlas/core/loop.py` | Model routing context |
| `src/atlas/observation/engine.py` | reply_to routing, messaging adapter map |
| `src/atlas/integrations/dashboard.py` | Token usage API endpoint |
| `tests/unit/messaging/test_telegram.py` | **New** |
| `tests/unit/control/test_token_tracker.py` | **New** |
| `tests/unit/skills/test_http_request.py` | **New** |
| `tests/integration/test_messaging_flow.py` | **New** |

---

## 10. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Telegram bot token leaked | Store in vault, never in config YAML. Env var fallback. |
| Unauthorized users send goals | **Mandatory** `allowed_user_ids` whitelist. No exceptions. |
| SSRF via http.request skill | Block localhost/private IP ranges. URL allowlist in policy engine. |
| Token budget burned by cron storms | Budget check before every goal execution. Daily cap is hard limit. |
| Long-running goals block messaging | Goals execute in asyncio tasks, adapter stays responsive. Typing indicator shows processing. |
| Telegram API rate limits | python-telegram-bot handles backoff internally. Message splitting for >4096 chars. |
| `python-telegram-bot` library breaks | Pin version. Adapter ABC means we can swap to raw HTTP if needed. |

---

## 11. What This Does NOT Cover

- **End-to-end encryption** — Telegram messages are server-encrypted, not E2E. Sensitive data should use Signal (Phase D).
- **Multi-user** — This is a single-user personal agent. `allowed_user_ids` is a whitelist, not a multi-tenant system.
- **OAuth flows** — Composio/Google OAuth is Phase D. The `http.request` skill can use pre-obtained tokens from vault.
- **Voice/media** — Telegram voice messages, images, documents are not handled. Text only for Phase B.
- **Frontend dashboard** — HTTP API endpoints exist but no UI. Phase 2+ concern.

---

## 12. Success Criteria

When this is done, a user should be able to:

1. **Send a Telegram message** "summarize my emails" → get a response back in Telegram
2. **Set up a morning briefing** cron that fires at 7am and sends a summary to Telegram
3. **Call any REST API** from a goal via the `http.request` skill (Whoop, weather, etc.)
4. **See daily token spend** and have goals blocked when budget is hit
5. **Route models** — cron jobs use Haiku, interactive goals use Sonnet

This matches the Reddit user's core setup minus the bespoke Composio OAuth (which is achievable via `http.request` + vault-stored tokens as a stopgap).
