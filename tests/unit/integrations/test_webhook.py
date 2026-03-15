import hashlib
import hmac as hmac_mod

import pytest
from atlas.integrations.webhook import WebhookServer
from atlas.integrations.event_bridge import EventBridge
from atlas.contracts.types import EventType, ObservationEvent


async def _noop_callback(e):
    pass


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


async def test_webhook_rejects_invalid_signature(aiohttp_client):
    bridge = EventBridge()
    bridge.register_parser("github", lambda et, p: ObservationEvent(
        event_type=EventType.WEBHOOK, source="github", payload=p,
    ))
    server = WebhookServer(
        event_bridge=bridge, event_callback=_noop_callback,
        secrets={"github": "my-secret"},
    )
    client = await aiohttp_client(server.create_app())
    resp = await client.post(
        "/webhooks/github", json={"action": "opened"},
        headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": "sha256=bad"},
    )
    assert resp.status == 403


async def test_webhook_accepts_valid_signature(aiohttp_client):
    bridge = EventBridge()
    bridge.register_parser("github", lambda et, p: ObservationEvent(
        event_type=EventType.WEBHOOK, source="github", payload=p,
    ))
    received = []
    server = WebhookServer(
        event_bridge=bridge,
        event_callback=lambda e: received.append(e),
        secrets={"github": "my-secret"},
    )
    client = await aiohttp_client(server.create_app())
    body = b'{"action":"opened"}'
    sig = "sha256=" + hmac_mod.new(b"my-secret", body, hashlib.sha256).hexdigest()
    resp = await client.post(
        "/webhooks/github", data=body,
        headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )
    assert resp.status == 200
    assert len(received) == 1
