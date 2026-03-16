import pytest
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
