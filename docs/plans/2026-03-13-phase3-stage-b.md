# Phase 3 Stage B: GitHub Connector + Webhook Ingestion + Dashboard API

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the first external integration (GitHub), a webhook HTTP endpoint for receiving real-time events, and a Dashboard API for monitoring ATLAS state — all running inside the daemon process.

**Architecture:** Three components share a single `aiohttp` web application bound to `127.0.0.1`. The `WebhookServer` receives incoming HTTP payloads and routes them through `EventBridge` to normalize into `ObservationEvent` objects for the existing reactive pipeline. `GitHubConnector` implements the new `ConnectorABC` base class, handling both inbound events (via webhooks) and outbound actions (via GitHub API). `DashboardServer` mounts REST endpoints on the same `aiohttp` app to serve JSON from existing SQLite stores. The `entity_mapper` table provides bidirectional mapping between ATLAS IDs and external service IDs.

**Tech Stack:** Python 3.12, aiohttp (new), httpx (existing), aiosqlite (existing)

---

### Task 1: Add aiohttp dependency and WebhookConfig

**Files:**
- Modify: `pyproject.toml:10-17`
- Modify: `src/atlas/config.py`
- Modify: `config/default.yaml`
- Test: `tests/unit/test_config.py`

**Step 1: Write the failing test**

Add to `tests/unit/test_config.py`:

```python
def test_webhook_config_defaults():
    from atlas.config import WebhookConfig
    cfg = WebhookConfig()
    assert cfg.enabled is True
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8484
    assert cfg.webhook_path_prefix == "/webhooks"
    assert cfg.dashboard_enabled is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_config.py::test_webhook_config_defaults -v`
Expected: FAIL with `ImportError: cannot import name 'WebhookConfig'`

**Step 3: Write minimal implementation**

Add to `src/atlas/config.py` after `MCPConfig` (after line 58):

```python
@dataclass
class WebhookConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8484
    webhook_path_prefix: str = "/webhooks"
    dashboard_enabled: bool = True
```

Add to `AtlasConfig`:

```python
    webhook: WebhookConfig = field(default_factory=WebhookConfig)
```

Add to `_SECTION_MAP`:

```python
    "webhook": WebhookConfig,
```

Add to `pyproject.toml` dependencies:

```toml
    "aiohttp>=3.10",
```

Add to `config/default.yaml`:

```yaml
webhook:
  enabled: true
  host: "127.0.0.1"
  port: 8484
  webhook_path_prefix: "/webhooks"
  dashboard_enabled: true
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_config.py -v`
Expected: PASS

**Step 5: Install and commit**

```bash
pip install -e ".[dev]"
git add pyproject.toml src/atlas/config.py config/default.yaml tests/unit/test_config.py
git commit -m "feat: add aiohttp dependency and WebhookConfig"
```

---

### Task 2: Add entity_mappings table to DatabaseStore

**Files:**
- Modify: `src/atlas/memory/store.py:110-119`
- Test: `tests/unit/memory/test_store_entity.py` (new)

**Step 1: Write the failing test**

Create `tests/unit/memory/test_store_entity.py`:

```python
import pytest
from atlas.memory.store import DatabaseStore


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


async def test_entity_mappings_table_exists(db):
    cursor = await db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='entity_mappings'"
    )
    row = await cursor.fetchone()
    assert row is not None


async def test_entity_mappings_columns(db):
    cursor = await db.db.execute("PRAGMA table_info(entity_mappings)")
    columns = {row[1] for row in await cursor.fetchall()}
    assert "service" in columns
    assert "external_id" in columns
    assert "atlas_type" in columns
    assert "atlas_id" in columns
    assert "metadata" in columns
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/memory/test_store_entity.py -v`
Expected: FAIL — table `entity_mappings` does not exist

**Step 3: Write minimal implementation**

Add to `src/atlas/memory/store.py` inside `_create_tables`, after the credentials table:

```sql
            CREATE TABLE IF NOT EXISTS entity_mappings (
                service TEXT NOT NULL,
                external_id TEXT NOT NULL,
                atlas_type TEXT NOT NULL,
                atlas_id TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                PRIMARY KEY (service, external_id)
            );

            CREATE INDEX IF NOT EXISTS idx_entity_atlas
                ON entity_mappings(atlas_type, atlas_id);
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/memory/test_store_entity.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/atlas/memory/store.py tests/unit/memory/test_store_entity.py
git commit -m "feat: add entity_mappings table to DatabaseStore schema"
```

---

### Task 3: Implement EntityMapper

**Files:**
- Create: `src/atlas/integrations/entity_mapper.py`
- Test: `tests/unit/integrations/test_entity_mapper.py` (new)

**Step 1: Write the failing test**

Create `tests/unit/integrations/test_entity_mapper.py`:

```python
import pytest
from atlas.integrations.entity_mapper import EntityMapper
from atlas.memory.store import DatabaseStore


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def mapper(db):
    return EntityMapper(db=db)


async def test_link_and_get_atlas_id(mapper):
    await mapper.link("github", "PR-123", "mission", "mission-abc")
    result = await mapper.get_atlas_id("github", "PR-123")
    assert result == ("mission", "mission-abc")


async def test_get_external_id(mapper):
    await mapper.link("github", "ISSUE-456", "task", "task-xyz")
    result = await mapper.get_external_id("github", "task", "task-xyz")
    assert result == "ISSUE-456"


async def test_get_atlas_id_not_found(mapper):
    result = await mapper.get_atlas_id("github", "nonexistent")
    assert result is None


async def test_get_external_id_not_found(mapper):
    result = await mapper.get_external_id("github", "mission", "nonexistent")
    assert result is None


async def test_unlink(mapper):
    await mapper.link("github", "PR-123", "mission", "mission-abc")
    await mapper.unlink("github", "PR-123")
    result = await mapper.get_atlas_id("github", "PR-123")
    assert result is None


async def test_link_with_metadata(mapper):
    await mapper.link("github", "PR-123", "mission", "m-1", metadata={"repo": "owner/repo"})
    result = await mapper.get_atlas_id("github", "PR-123")
    assert result == ("mission", "m-1")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/integrations/test_entity_mapper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'atlas.integrations.entity_mapper'`

**Step 3: Write minimal implementation**

Create `src/atlas/integrations/entity_mapper.py`:

```python
"""Entity Mapper — bidirectional mapping between ATLAS IDs and external service IDs."""
import json
import logging
from datetime import datetime, timezone

from atlas.memory.store import DatabaseStore

logger = logging.getLogger(__name__)


class EntityMapper:
    """Maps external service entities to ATLAS entities and vice versa."""

    def __init__(self, db: DatabaseStore):
        self._db = db

    async def link(
        self,
        service: str,
        external_id: str,
        atlas_type: str,
        atlas_id: str,
        metadata: dict | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.db.execute(
            """INSERT INTO entity_mappings (service, external_id, atlas_type, atlas_id, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(service, external_id) DO UPDATE SET
                atlas_type=excluded.atlas_type,
                atlas_id=excluded.atlas_id,
                metadata=excluded.metadata""",
            (service, external_id, atlas_type, atlas_id, json.dumps(metadata or {}), now),
        )
        await self._db.db.commit()

    async def get_atlas_id(self, service: str, external_id: str) -> tuple[str, str] | None:
        cursor = await self._db.db.execute(
            "SELECT atlas_type, atlas_id FROM entity_mappings WHERE service=? AND external_id=?",
            (service, external_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return (row[0], row[1])

    async def get_external_id(self, service: str, atlas_type: str, atlas_id: str) -> str | None:
        cursor = await self._db.db.execute(
            "SELECT external_id FROM entity_mappings WHERE service=? AND atlas_type=? AND atlas_id=?",
            (service, atlas_type, atlas_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return row[0]

    async def unlink(self, service: str, external_id: str) -> None:
        await self._db.db.execute(
            "DELETE FROM entity_mappings WHERE service=? AND external_id=?",
            (service, external_id),
        )
        await self._db.db.commit()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/integrations/test_entity_mapper.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/atlas/integrations/entity_mapper.py tests/unit/integrations/test_entity_mapper.py
git commit -m "feat: implement EntityMapper for bidirectional ID mapping"
```

---

### Task 4: Implement ConnectorABC base class

**Files:**
- Create: `src/atlas/integrations/connector.py`
- Test: `tests/unit/integrations/test_connector.py` (new)

**Step 1: Write the failing test**

Create `tests/unit/integrations/test_connector.py`:

```python
import asyncio
import time
import pytest
from atlas.integrations.connector import ConnectorABC


class FakeConnector(ConnectorABC):
    """Concrete test implementation of ConnectorABC."""

    def __init__(self):
        super().__init__(service_name="fake", rate_limit_rpm=60)
        self.auth_called = False

    async def authenticate(self) -> None:
        self.auth_called = True

    async def handle_event(self, event_type: str, payload: dict) -> dict:
        return {"handled": event_type}

    async def execute_action(self, action: str, params: dict) -> dict:
        await self._check_rate_limit()
        return {"action": action, "params": params}


def test_connector_has_service_name():
    conn = FakeConnector()
    assert conn.service_name == "fake"


async def test_authenticate():
    conn = FakeConnector()
    await conn.authenticate()
    assert conn.auth_called is True


async def test_handle_event():
    conn = FakeConnector()
    result = await conn.handle_event("push", {"ref": "main"})
    assert result == {"handled": "push"}


async def test_execute_action():
    conn = FakeConnector()
    result = await conn.execute_action("comment", {"body": "hello"})
    assert result == {"action": "comment", "params": {"body": "hello"}}


async def test_rate_limit_tracks_calls():
    conn = FakeConnector()
    # Should not raise for first call
    result = await conn.execute_action("comment", {"body": "test"})
    assert result["action"] == "comment"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/integrations/test_connector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'atlas.integrations.connector'`

**Step 3: Write minimal implementation**

Create `src/atlas/integrations/connector.py`:

```python
"""Connector ABC — base class for external service integrations."""
import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class ConnectorABC(ABC):
    """Base class for all external service connectors.

    Provides rate limiting and a standard interface for authentication,
    event handling, and action execution.
    """

    def __init__(self, service_name: str, rate_limit_rpm: int = 60):
        self._service_name = service_name
        self._rate_limit_rpm = rate_limit_rpm
        self._call_timestamps: list[float] = []

    @property
    def service_name(self) -> str:
        return self._service_name

    @abstractmethod
    async def authenticate(self) -> None:
        """Authenticate with the external service."""
        ...

    @abstractmethod
    async def handle_event(self, event_type: str, payload: dict) -> dict:
        """Handle an incoming event from the external service."""
        ...

    @abstractmethod
    async def execute_action(self, action: str, params: dict) -> dict:
        """Execute an outbound action on the external service."""
        ...

    async def _check_rate_limit(self) -> None:
        """Wait if rate limit would be exceeded."""
        now = time.monotonic()
        window = 60.0  # 1 minute window
        # Prune old timestamps
        self._call_timestamps = [t for t in self._call_timestamps if now - t < window]
        if len(self._call_timestamps) >= self._rate_limit_rpm:
            wait_time = window - (now - self._call_timestamps[0])
            if wait_time > 0:
                logger.warning(
                    "%s rate limit reached (%d rpm), waiting %.1fs",
                    self._service_name, self._rate_limit_rpm, wait_time,
                )
                await asyncio.sleep(wait_time)
        self._call_timestamps.append(time.monotonic())
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/integrations/test_connector.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/atlas/integrations/connector.py tests/unit/integrations/test_connector.py
git commit -m "feat: implement ConnectorABC base class with rate limiting"
```

---

### Task 5: Implement EventBridge

**Files:**
- Create: `src/atlas/integrations/event_bridge.py`
- Test: `tests/unit/integrations/test_event_bridge.py` (new)

**Step 1: Write the failing test**

Create `tests/unit/integrations/test_event_bridge.py`:

```python
import hashlib
import hmac
import json
import pytest
from atlas.integrations.event_bridge import EventBridge
from atlas.contracts.types import EventType, ObservationEvent


def test_register_parser():
    bridge = EventBridge()
    bridge.register_parser("github", lambda et, p: ObservationEvent(
        event_type=EventType.WEBHOOK, source="github", payload=p,
    ))
    assert "github" in bridge.parsers


def test_parse_event():
    bridge = EventBridge()
    bridge.register_parser("github", lambda et, p: ObservationEvent(
        event_type=EventType.WEBHOOK, source="github", payload=p,
    ))
    event = bridge.parse("github", "push", {"ref": "refs/heads/main"})
    assert event is not None
    assert event.event_type == EventType.WEBHOOK
    assert event.source == "github"
    assert event.payload == {"ref": "refs/heads/main"}


def test_parse_unknown_service_returns_none():
    bridge = EventBridge()
    event = bridge.parse("unknown_service", "push", {})
    assert event is None


def test_verify_github_signature():
    bridge = EventBridge()
    secret = "test-secret"
    body = b'{"action":"opened"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert bridge.verify_signature("github", body, sig, secret) is True


def test_verify_github_signature_invalid():
    bridge = EventBridge()
    assert bridge.verify_signature("github", b"body", "sha256=invalid", "secret") is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/integrations/test_event_bridge.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `src/atlas/integrations/event_bridge.py`:

```python
"""Event Bridge — normalizes external webhook payloads into ObservationEvents."""
import hashlib
import hmac
import logging
from typing import Any, Callable

from atlas.contracts.types import EventType, ObservationEvent

logger = logging.getLogger(__name__)

# Parser signature: (event_type: str, payload: dict) -> ObservationEvent
EventParser = Callable[[str, dict[str, Any]], ObservationEvent]


class EventBridge:
    """Normalizes raw webhook payloads from different services into ObservationEvents."""

    def __init__(self):
        self._parsers: dict[str, EventParser] = {}

    @property
    def parsers(self) -> dict[str, EventParser]:
        return dict(self._parsers)

    def register_parser(self, service: str, parser: EventParser) -> None:
        self._parsers[service] = parser
        logger.info("Registered event parser for %s", service)

    def parse(self, service: str, event_type: str, payload: dict) -> ObservationEvent | None:
        parser = self._parsers.get(service)
        if parser is None:
            logger.warning("No parser registered for service: %s", service)
            return None
        try:
            return parser(event_type, payload)
        except Exception as e:
            logger.error("Failed to parse event from %s: %s", service, e)
            return None

    def verify_signature(
        self, service: str, body: bytes, signature: str, secret: str
    ) -> bool:
        """Verify webhook signature. Currently supports GitHub HMAC-SHA256."""
        if service == "github":
            return self._verify_github(body, signature, secret)
        # Default: no verification available
        logger.warning("No signature verification for service: %s", service)
        return True

    def _verify_github(self, body: bytes, signature: str, secret: str) -> bool:
        if not signature.startswith("sha256="):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature[7:], expected)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/integrations/test_event_bridge.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/atlas/integrations/event_bridge.py tests/unit/integrations/test_event_bridge.py
git commit -m "feat: implement EventBridge for webhook payload normalization"
```

---

### Task 6: Implement WebhookServer

**Files:**
- Create: `src/atlas/integrations/webhook.py`
- Test: `tests/unit/integrations/test_webhook.py` (new)

**Step 1: Write the failing test**

Create `tests/unit/integrations/test_webhook.py`:

```python
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer
from atlas.integrations.webhook import WebhookServer
from atlas.integrations.event_bridge import EventBridge
from atlas.contracts.types import EventType, ObservationEvent


@pytest.fixture
def bridge():
    b = EventBridge()
    b.register_parser("github", lambda et, p: ObservationEvent(
        event_type=EventType.WEBHOOK,
        source="github",
        payload={**p, "github_event": et},
    ))
    return b


@pytest.fixture
def received_events():
    return []


@pytest.fixture
async def webhook_server(bridge, received_events):
    async def on_event(event: ObservationEvent) -> None:
        received_events.append(event)

    server = WebhookServer(
        event_bridge=bridge,
        event_callback=on_event,
        webhook_path_prefix="/webhooks",
    )
    return server


async def test_webhook_app_has_routes(webhook_server):
    app = webhook_server.create_app()
    routes = [r.resource.canonical for r in app.router.routes() if hasattr(r, "resource")]
    assert "/webhooks/{service}" in routes


async def test_webhook_handles_github_post(webhook_server, received_events, aiohttp_client):
    app = webhook_server.create_app()
    client = await aiohttp_client(app)

    resp = await client.post(
        "/webhooks/github",
        json={"action": "opened", "number": 42},
        headers={"X-GitHub-Event": "pull_request"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "accepted"
    assert len(received_events) == 1
    assert received_events[0].payload["action"] == "opened"


async def test_webhook_unknown_service(webhook_server, aiohttp_client):
    app = webhook_server.create_app()
    client = await aiohttp_client(app)

    resp = await client.post(
        "/webhooks/unknown_svc",
        json={"data": "test"},
    )
    assert resp.status == 400


async def test_health_endpoint(webhook_server, aiohttp_client):
    app = webhook_server.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/health")
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "ok"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/integrations/test_webhook.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `src/atlas/integrations/webhook.py`:

```python
"""Webhook Server — HTTP endpoint for receiving webhook payloads from external services."""
import logging
from typing import Any, Callable, Coroutine

from aiohttp import web

from atlas.contracts.types import ObservationEvent
from atlas.integrations.event_bridge import EventBridge

logger = logging.getLogger(__name__)

EventCallback = Callable[[ObservationEvent], Coroutine[Any, Any, None]]


class WebhookServer:
    """Lightweight aiohttp server for webhook ingestion."""

    def __init__(
        self,
        event_bridge: EventBridge,
        event_callback: EventCallback,
        webhook_path_prefix: str = "/webhooks",
    ):
        self._bridge = event_bridge
        self._callback = event_callback
        self._prefix = webhook_path_prefix
        self._app: web.Application | None = None

    def create_app(self) -> web.Application:
        app = web.Application()
        app.router.add_post(f"{self._prefix}/{{service}}", self._handle_webhook)
        app.router.add_get("/health", self._handle_health)
        self._app = app
        return app

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        service = request.match_info["service"]
        try:
            payload = await request.json()
        except Exception:
            return web.json_response(
                {"status": "error", "message": "invalid JSON"}, status=400,
            )

        # Extract event type from headers (service-specific)
        event_type = self._extract_event_type(service, request)

        event = self._bridge.parse(service, event_type, payload)
        if event is None:
            return web.json_response(
                {"status": "error", "message": f"no parser for service: {service}"},
                status=400,
            )

        # Fire-and-forget to the callback
        try:
            await self._callback(event)
        except Exception as e:
            logger.error("Event callback failed for %s: %s", service, e)

        return web.json_response({"status": "accepted", "event_id": event.event_id})

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    def _extract_event_type(self, service: str, request: web.Request) -> str:
        if service == "github":
            return request.headers.get("X-GitHub-Event", "unknown")
        if service == "slack":
            return request.headers.get("X-Slack-Event", "unknown")
        return "unknown"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/integrations/test_webhook.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/atlas/integrations/webhook.py tests/unit/integrations/test_webhook.py
git commit -m "feat: implement WebhookServer for HTTP webhook ingestion"
```

---

### Task 7: Implement GitHubConnector

**Files:**
- Create: `src/atlas/integrations/connectors/github.py`
- Test: `tests/unit/integrations/test_github.py` (new)

**Step 1: Write the failing test**

Create `tests/unit/integrations/test_github.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from atlas.integrations.connectors.github import GitHubConnector
from atlas.contracts.types import EventType, ObservationEvent


@pytest.fixture
def connector():
    return GitHubConnector(token="ghp_test_token_123", owner="test-owner", repo="test-repo")


def test_service_name(connector):
    assert connector.service_name == "github"


def test_event_parser_returns_observation_event(connector):
    parser = connector.get_event_parser()
    event = parser("pull_request", {"action": "opened", "number": 42})
    assert isinstance(event, ObservationEvent)
    assert event.event_type == EventType.WEBHOOK
    assert event.source == "github"
    assert event.payload["action"] == "opened"
    assert event.payload["github_event"] == "pull_request"


def test_event_parser_push_event(connector):
    parser = connector.get_event_parser()
    event = parser("push", {"ref": "refs/heads/main", "commits": []})
    assert event.payload["github_event"] == "push"
    assert event.payload["ref"] == "refs/heads/main"


async def test_authenticate_sets_headers(connector):
    await connector.authenticate()
    assert connector._headers["Authorization"] == "Bearer ghp_test_token_123"
    assert "Accept" in connector._headers


async def test_execute_action_comment(connector):
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"id": 1, "body": "test comment"}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        result = await connector.execute_action("comment", {
            "issue_number": 1,
            "body": "test comment",
        })
    assert result["status"] == "success"


async def test_execute_action_unknown(connector):
    result = await connector.execute_action("unknown_action", {})
    assert result["status"] == "error"
    assert "unsupported" in result["error"].lower()


async def test_handle_event_pr_opened(connector):
    result = await connector.handle_event("pull_request", {
        "action": "opened",
        "number": 42,
        "pull_request": {"title": "Fix bug"},
    })
    assert result["handled"] is True
    assert result["event_type"] == "pull_request"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/integrations/test_github.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `src/atlas/integrations/connectors/github.py`:

```python
"""GitHub Connector — handles GitHub API interactions and webhook events."""
import logging
from typing import Any, Callable

import httpx

from atlas.contracts.types import EventType, ObservationEvent
from atlas.integrations.connector import ConnectorABC

logger = logging.getLogger(__name__)


class GitHubConnector(ConnectorABC):
    """Connector for GitHub API and webhook events."""

    def __init__(
        self,
        token: str,
        owner: str = "",
        repo: str = "",
        api_base: str = "https://api.github.com",
        rate_limit_rpm: int = 60,
    ):
        super().__init__(service_name="github", rate_limit_rpm=rate_limit_rpm)
        self._token = token
        self._owner = owner
        self._repo = repo
        self._api_base = api_base
        self._headers: dict[str, str] = {}

    async def authenticate(self) -> None:
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        logger.info("GitHub connector authenticated for %s/%s", self._owner, self._repo)

    async def handle_event(self, event_type: str, payload: dict) -> dict:
        logger.info("GitHub event: %s action=%s", event_type, payload.get("action", ""))
        return {"handled": True, "event_type": event_type}

    async def execute_action(self, action: str, params: dict) -> dict:
        await self._check_rate_limit()

        match action:
            case "comment":
                return await self._post_comment(params)
            case "create_issue":
                return await self._create_issue(params)
            case "list_pulls":
                return await self._list_pulls(params)
            case _:
                return {"status": "error", "error": f"Unsupported action: {action}"}

    def get_event_parser(self) -> Callable[[str, dict], ObservationEvent]:
        """Return an EventBridge-compatible parser for GitHub webhooks."""
        def parser(event_type: str, payload: dict[str, Any]) -> ObservationEvent:
            return ObservationEvent(
                event_type=EventType.WEBHOOK,
                source="github",
                payload={**payload, "github_event": event_type},
                priority=self._event_priority(event_type, payload),
            )
        return parser

    async def _post_comment(self, params: dict) -> dict:
        issue_number = params.get("issue_number")
        body = params.get("body", "")
        url = f"{self._api_base}/repos/{self._owner}/{self._repo}/issues/{issue_number}/comments"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json={"body": body}, headers=self._headers)
                resp.raise_for_status()
                return {"status": "success", "data": resp.json()}
        except httpx.HTTPError as e:
            return {"status": "error", "error": str(e)}

    async def _create_issue(self, params: dict) -> dict:
        url = f"{self._api_base}/repos/{self._owner}/{self._repo}/issues"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=params, headers=self._headers)
                resp.raise_for_status()
                return {"status": "success", "data": resp.json()}
        except httpx.HTTPError as e:
            return {"status": "error", "error": str(e)}

    async def _list_pulls(self, params: dict) -> dict:
        url = f"{self._api_base}/repos/{self._owner}/{self._repo}/pulls"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=self._headers, params=params)
                resp.raise_for_status()
                return {"status": "success", "data": resp.json()}
        except httpx.HTTPError as e:
            return {"status": "error", "error": str(e)}

    def _event_priority(self, event_type: str, payload: dict) -> int:
        """Assign priority based on event type. Lower number = higher priority."""
        match event_type:
            case "check_run" | "check_suite":
                if payload.get("action") == "completed" and payload.get("conclusion") == "failure":
                    return 2  # CI failure = high priority
            case "pull_request":
                return 4
            case "issues":
                return 5
            case "push":
                return 6
        return 5  # default
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/integrations/test_github.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/atlas/integrations/connectors/github.py tests/unit/integrations/test_github.py
git commit -m "feat: implement GitHubConnector with event parsing and API actions"
```

---

### Task 8: Implement DashboardServer

**Files:**
- Create: `src/atlas/integrations/dashboard.py`
- Test: `tests/unit/integrations/test_dashboard.py` (new)

**Step 1: Write the failing test**

Create `tests/unit/integrations/test_dashboard.py`:

```python
import json
import pytest
from aiohttp.test_utils import TestClient
from atlas.integrations.dashboard import DashboardServer
from atlas.memory.store import DatabaseStore
from atlas.control.audit import AuditLogger
from atlas.skills.registry import SkillRegistry
from atlas.contracts.types import AuditEntry, PolicyDecision


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def audit(db):
    a = AuditLogger(db=db.db)
    await a.initialize()
    return a


@pytest.fixture
def registry():
    reg = SkillRegistry()
    return reg


@pytest.fixture
def received_goals():
    return []


@pytest.fixture
async def dashboard(db, audit, registry, received_goals):
    async def goal_handler(goal_text: str) -> dict:
        received_goals.append(goal_text)
        return {"status": "accepted"}

    server = DashboardServer(
        db=db,
        audit=audit,
        registry=registry,
        goal_handler=goal_handler,
    )
    return server


async def test_status_endpoint(dashboard, aiohttp_client):
    app = dashboard.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/status")
    assert resp.status == 200
    data = await resp.json()
    assert "uptime_seconds" in data


async def test_missions_endpoint(dashboard, aiohttp_client):
    app = dashboard.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/missions")
    assert resp.status == 200
    data = await resp.json()
    assert isinstance(data, list)


async def test_skills_endpoint(dashboard, registry, aiohttp_client):
    async def noop(p):
        return {}
    registry.register("test.skill", "Test Skill", "A test", noop, "low")

    app = dashboard.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/skills")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 1
    assert data[0]["skill_id"] == "test.skill"


async def test_audit_endpoint(dashboard, audit, aiohttp_client):
    await audit.log(AuditEntry(
        actor="test",
        action_type="test_action",
        outcome="success",
        policy_decision=PolicyDecision.ALLOW,
    ))

    app = dashboard.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/audit")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) >= 1
    assert data[0]["actor"] == "test"


async def test_audit_pagination(dashboard, aiohttp_client):
    app = dashboard.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/audit?limit=5")
    assert resp.status == 200


async def test_goal_endpoint(dashboard, received_goals, aiohttp_client):
    app = dashboard.create_app()
    client = await aiohttp_client(app)

    resp = await client.post("/api/goal", json={"goal_text": "fix the bug"})
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "accepted"
    assert received_goals == ["fix the bug"]


async def test_goal_endpoint_missing_body(dashboard, aiohttp_client):
    app = dashboard.create_app()
    client = await aiohttp_client(app)

    resp = await client.post("/api/goal", json={})
    assert resp.status == 400


async def test_memory_stats_endpoint(dashboard, aiohttp_client):
    app = dashboard.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/memory/stats")
    assert resp.status == 200
    data = await resp.json()
    assert "episode_count" in data
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/integrations/test_dashboard.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `src/atlas/integrations/dashboard.py`:

```python
"""Dashboard API — HTTP REST endpoints for monitoring and control."""
import logging
import time
from typing import Any, Callable, Coroutine

from aiohttp import web

from atlas.control.audit import AuditLogger
from atlas.memory.store import DatabaseStore
from atlas.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

GoalHandler = Callable[[str], Coroutine[Any, Any, dict]]

_start_time = time.monotonic()


class DashboardServer:
    """REST API for monitoring ATLAS state."""

    def __init__(
        self,
        db: DatabaseStore,
        audit: AuditLogger,
        registry: SkillRegistry,
        goal_handler: GoalHandler | None = None,
    ):
        self._db = db
        self._audit = audit
        self._registry = registry
        self._goal_handler = goal_handler

    def create_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/api/status", self._handle_status)
        app.router.add_get("/api/missions", self._handle_missions)
        app.router.add_get("/api/skills", self._handle_skills)
        app.router.add_get("/api/memory/stats", self._handle_memory_stats)
        app.router.add_get("/api/audit", self._handle_audit)
        app.router.add_post("/api/goal", self._handle_goal)
        return app

    async def _handle_status(self, request: web.Request) -> web.Response:
        uptime = time.monotonic() - _start_time
        return web.json_response({
            "status": "running",
            "uptime_seconds": round(uptime, 1),
        })

    async def _handle_missions(self, request: web.Request) -> web.Response:
        cursor = await self._db.db.execute(
            "SELECT mission_id, goal_text, status, created_at, updated_at "
            "FROM missions ORDER BY created_at DESC LIMIT 50"
        )
        rows = await cursor.fetchall()
        missions = [
            {
                "mission_id": r[0], "goal_text": r[1], "status": r[2],
                "created_at": r[3], "updated_at": r[4],
            }
            for r in rows
        ]
        return web.json_response(missions)

    async def _handle_skills(self, request: web.Request) -> web.Response:
        skills = self._registry.list_all()
        data = [
            {
                "skill_id": s.skill_id,
                "name": s.name,
                "description": s.description,
                "risk_level": s.risk_level.value,
                "tags": s.tags,
            }
            for s in skills
        ]
        return web.json_response(data)

    async def _handle_memory_stats(self, request: web.Request) -> web.Response:
        episode_cursor = await self._db.db.execute("SELECT COUNT(*) FROM episodes")
        episode_count = (await episode_cursor.fetchone())[0]

        mission_cursor = await self._db.db.execute("SELECT COUNT(*) FROM missions")
        mission_count = (await mission_cursor.fetchone())[0]

        return web.json_response({
            "episode_count": episode_count,
            "mission_count": mission_count,
        })

    async def _handle_audit(self, request: web.Request) -> web.Response:
        limit = int(request.query.get("limit", "50"))
        entries = await self._audit.query(limit=limit)
        return web.json_response(entries)

    async def _handle_goal(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response(
                {"status": "error", "message": "invalid JSON"}, status=400,
            )
        goal_text = body.get("goal_text")
        if not goal_text:
            return web.json_response(
                {"status": "error", "message": "goal_text is required"}, status=400,
            )
        if not self._goal_handler:
            return web.json_response(
                {"status": "error", "message": "no goal handler configured"}, status=500,
            )
        result = await self._goal_handler(goal_text)
        return web.json_response(result)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/integrations/test_dashboard.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/atlas/integrations/dashboard.py tests/unit/integrations/test_dashboard.py
git commit -m "feat: implement DashboardServer with REST endpoints for monitoring"
```

---

### Task 9: Wire webhook + dashboard into daemon lifecycle

**Files:**
- Modify: `src/atlas/cli.py:281-377` (_run_daemon)
- Modify: `src/atlas/daemon/loop.py`
- Test: manual validation (daemon wiring is tested via existing daemon tests + integration)

**Step 1: Write the failing test**

Create `tests/unit/integrations/test_daemon_wiring.py`:

```python
"""Test that the webhook/dashboard app factory works with daemon components."""
import pytest
from aiohttp import web
from atlas.integrations.webhook import WebhookServer
from atlas.integrations.dashboard import DashboardServer
from atlas.integrations.event_bridge import EventBridge
from atlas.memory.store import DatabaseStore
from atlas.control.audit import AuditLogger
from atlas.skills.registry import SkillRegistry


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


async def test_combined_app_has_all_routes(db):
    """Both webhook and dashboard routes exist on the same aiohttp app."""
    bridge = EventBridge()
    audit = AuditLogger(db=db.db)
    await audit.initialize()
    registry = SkillRegistry()

    async def noop_event(e):
        pass

    async def noop_goal(g):
        return {"status": "ok"}

    webhook = WebhookServer(event_bridge=bridge, event_callback=noop_event)
    dashboard = DashboardServer(db=db, audit=audit, registry=registry, goal_handler=noop_goal)

    # Create combined app
    app = web.Application()
    webhook_app = webhook.create_app()
    dashboard_app = dashboard.create_app()

    # Mount sub-apps or merge routes
    for route in webhook_app.router.routes():
        if hasattr(route, "resource") and hasattr(route.resource, "canonical"):
            info = route.get_info()
            if "formatter" in info:
                app.router.add_route(route.method, info["formatter"], route.handler)

    for route in dashboard_app.router.routes():
        if hasattr(route, "resource") and hasattr(route.resource, "canonical"):
            info = route.get_info()
            if "formatter" in info:
                app.router.add_route(route.method, info["formatter"], route.handler)

    # Verify key routes exist
    route_paths = set()
    for resource in app.router.resources():
        if hasattr(resource, "canonical"):
            route_paths.add(resource.canonical)

    assert "/webhooks/{service}" in route_paths or len(route_paths) > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/integrations/test_daemon_wiring.py -v`
Expected: FAIL (import or route error)

**Step 3: Write minimal implementation**

Modify `src/atlas/daemon/loop.py` to accept an optional `aiohttp` app runner:

Add a new parameter to `DaemonLoop.__init__`:

```python
    def __init__(
        self,
        socket_path: str,
        pid_path: str,
        goal_executor: Callable[..., Coroutine[Any, Any, dict]] | None = None,
        http_app: Any | None = None,
        http_host: str = "127.0.0.1",
        http_port: int = 8484,
    ):
        self._socket_path = socket_path
        self._pid_file = PidFile(pid_path)
        self._goal_executor = goal_executor
        self._server: DaemonSocketServer | None = None
        self._running = False
        self._start_time = 0.0
        self._http_app = http_app
        self._http_host = http_host
        self._http_port = http_port
        self._http_runner = None
```

In `start()`, after starting the socket server, add HTTP app startup:

```python
        # Start HTTP server if configured
        if self._http_app:
            from aiohttp import web
            self._http_runner = web.AppRunner(self._http_app)
            await self._http_runner.setup()
            site = web.TCPSite(self._http_runner, self._http_host, self._http_port)
            await site.start()
            logger.info("HTTP server started on %s:%d", self._http_host, self._http_port)
```

In the cleanup after the while loop, before `self._pid_file.remove()`:

```python
        if self._http_runner:
            await self._http_runner.cleanup()
```

Then modify `src/atlas/cli.py` `_run_daemon` to build and pass the HTTP app. Add after `obs_engine` setup (around line 365):

```python
    # Set up webhook + dashboard HTTP server
    from atlas.integrations.event_bridge import EventBridge
    from atlas.integrations.webhook import WebhookServer
    from atlas.integrations.dashboard import DashboardServer

    event_bridge = EventBridge()
    webhook_server = WebhookServer(
        event_bridge=event_bridge,
        event_callback=obs_engine._on_event,
        webhook_path_prefix=config.webhook.webhook_path_prefix if hasattr(config, 'webhook') else "/webhooks",
    )
    dashboard_server = DashboardServer(
        db=db,
        audit=audit,
        registry=registry,
        goal_handler=goal_executor,
    )

    # Build combined aiohttp app
    http_app = webhook_server.create_app()
    dashboard_app = dashboard_server.create_app()
    # Merge dashboard routes into webhook app
    for resource in dashboard_app.router.resources():
        for route in resource:
            http_app.router.add_route(route.method, resource.canonical, route.handler)
```

Update the `DaemonLoop` constructor call to pass the HTTP app:

```python
    daemon_loop = DaemonLoop(
        socket_path=socket_path,
        pid_path=pid_path,
        goal_executor=goal_executor,
        http_app=http_app,
        http_host=config.webhook.host if hasattr(config, 'webhook') else "127.0.0.1",
        http_port=config.webhook.port if hasattr(config, 'webhook') else 8484,
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/integrations/test_daemon_wiring.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/atlas/daemon/loop.py src/atlas/cli.py tests/unit/integrations/test_daemon_wiring.py
git commit -m "feat: wire webhook + dashboard HTTP server into daemon lifecycle"
```

---

### Task 10: Integration test — Webhook → EventBridge → ObservationEngine pipeline

**Files:**
- Create: `tests/integration/test_webhook_pipeline.py`

**Step 1: Write the integration test**

Create `tests/integration/test_webhook_pipeline.py`:

```python
"""Integration test: webhook payload → EventBridge → ObservationEngine pipeline."""
import pytest
from aiohttp.test_utils import TestClient
from atlas.integrations.event_bridge import EventBridge
from atlas.integrations.webhook import WebhookServer
from atlas.integrations.dashboard import DashboardServer
from atlas.integrations.connectors.github import GitHubConnector
from atlas.integrations.entity_mapper import EntityMapper
from atlas.contracts.types import EventType, ObservationEvent
from atlas.memory.store import DatabaseStore
from atlas.control.audit import AuditLogger
from atlas.skills.registry import SkillRegistry


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


async def test_github_webhook_to_observation_event(aiohttp_client):
    """POST to /webhooks/github produces an ObservationEvent with correct fields."""
    received = []

    async def on_event(event: ObservationEvent) -> None:
        received.append(event)

    connector = GitHubConnector(token="fake", owner="o", repo="r")
    bridge = EventBridge()
    bridge.register_parser("github", connector.get_event_parser())

    server = WebhookServer(event_bridge=bridge, event_callback=on_event)
    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.post(
        "/webhooks/github",
        json={"action": "opened", "number": 1, "pull_request": {"title": "Fix"}},
        headers={"X-GitHub-Event": "pull_request"},
    )
    assert resp.status == 200
    assert len(received) == 1
    event = received[0]
    assert event.event_type == EventType.WEBHOOK
    assert event.source == "github"
    assert event.payload["github_event"] == "pull_request"
    assert event.payload["action"] == "opened"


async def test_dashboard_reads_real_data(db, aiohttp_client):
    """Dashboard endpoints return data from real SQLite stores."""
    audit = AuditLogger(db=db.db)
    await audit.initialize()
    registry = SkillRegistry()

    async def noop(p):
        return {}
    registry.register("test.skill", "Test", "test skill", noop)

    dashboard = DashboardServer(db=db, audit=audit, registry=registry)
    app = dashboard.create_app()
    client = await aiohttp_client(app)

    # Check skills
    resp = await client.get("/api/skills")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 1
    assert data[0]["skill_id"] == "test.skill"

    # Check memory stats
    resp = await client.get("/api/memory/stats")
    assert resp.status == 200
    data = await resp.json()
    assert data["episode_count"] == 0

    # Check status
    resp = await client.get("/api/status")
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "running"


async def test_entity_mapper_round_trip(db):
    """EntityMapper stores and retrieves mappings correctly."""
    mapper = EntityMapper(db=db)
    await mapper.link("github", "PR-42", "mission", "m-abc-123")

    # Forward lookup
    result = await mapper.get_atlas_id("github", "PR-42")
    assert result == ("mission", "m-abc-123")

    # Reverse lookup
    ext_id = await mapper.get_external_id("github", "mission", "m-abc-123")
    assert ext_id == "PR-42"

    # Unlink
    await mapper.unlink("github", "PR-42")
    assert await mapper.get_atlas_id("github", "PR-42") is None
```

**Step 2: Run the integration test**

Run: `pytest tests/integration/test_webhook_pipeline.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/integration/test_webhook_pipeline.py
git commit -m "test: add integration tests for webhook pipeline and dashboard"
```

---

### Task 11: Run full test suite and lint

**Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 2: Run linter**

Run: `ruff check src/ tests/`
Expected: No errors (fix any that arise)

**Step 3: Final commit if any lint fixes needed**

```bash
git add -A
git commit -m "style: fix lint issues from Stage B implementation"
```

---

## Summary of files created/modified

**New files:**
- `src/atlas/integrations/connector.py` — ConnectorABC base class
- `src/atlas/integrations/entity_mapper.py` — EntityMapper
- `src/atlas/integrations/event_bridge.py` — EventBridge
- `src/atlas/integrations/webhook.py` — WebhookServer
- `src/atlas/integrations/dashboard.py` — DashboardServer
- `src/atlas/integrations/connectors/github.py` — GitHubConnector
- `tests/unit/integrations/test_connector.py`
- `tests/unit/integrations/test_entity_mapper.py`
- `tests/unit/integrations/test_event_bridge.py`
- `tests/unit/integrations/test_webhook.py`
- `tests/unit/integrations/test_github.py`
- `tests/unit/integrations/test_dashboard.py`
- `tests/unit/integrations/test_daemon_wiring.py`
- `tests/unit/memory/test_store_entity.py`
- `tests/integration/test_webhook_pipeline.py`

**Modified files:**
- `pyproject.toml` — aiohttp dependency
- `src/atlas/config.py` — WebhookConfig
- `config/default.yaml` — webhook section
- `src/atlas/memory/store.py` — entity_mappings table
- `src/atlas/daemon/loop.py` — HTTP app runner support
- `src/atlas/cli.py` — webhook + dashboard wiring in daemon
- `tests/unit/test_config.py` — WebhookConfig test
