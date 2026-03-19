"""Integration test: webhook payload → EventBridge → ObservationEngine pipeline."""

import pytest
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
