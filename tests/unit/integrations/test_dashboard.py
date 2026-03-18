import pytest
from atlas.integrations.dashboard import DashboardServer
from atlas.memory.store import DatabaseStore
from atlas.control.audit import AuditLogger
from atlas.control.emergency import EmergencyController
from atlas.control.approval_rules import ApprovalRuleStore
from atlas.control.trust import TrustTracker
from atlas.skills.registry import SkillRegistry
from atlas.contracts.types import ApprovalRule, AuditEntry, PolicyDecision


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


# --- Tests for new endpoints (full_dashboard fixture) ---


@pytest.fixture
async def full_dashboard(db, audit, registry, received_goals):
    from atlas.config import load_config
    config = load_config()

    async def goal_handler(goal_text: str) -> dict:
        received_goals.append(goal_text)
        return {"status": "accepted"}

    emergency = EmergencyController()
    rule_store = ApprovalRuleStore(db)
    trust_tracker = TrustTracker(
        db=db, escalation_threshold=10,
        demotion_failure_count=3, demotion_window_size=5,
    )

    server = DashboardServer(
        db=db, audit=audit, registry=registry,
        goal_handler=goal_handler,
        config=config,
        emergency_controller=emergency,
        approval_rule_store=rule_store,
        trust_tracker=trust_tracker,
    )
    return server, emergency, rule_store, trust_tracker


async def test_health_endpoint(full_dashboard, aiohttp_client):
    server, _, _, _ = full_dashboard
    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/health")
    assert resp.status == 200
    data = await resp.json()
    assert "database" in data


async def test_tasks_endpoint(full_dashboard, aiohttp_client):
    server, _, _, _ = full_dashboard
    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/tasks")
    assert resp.status == 200
    data = await resp.json()
    assert isinstance(data, list)


async def test_emergency_pause_endpoint(full_dashboard, aiohttp_client):
    server, emergency, _, _ = full_dashboard
    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.post("/api/emergency/pause")
    assert resp.status == 200
    assert emergency.is_paused is True


async def test_emergency_resume_endpoint(full_dashboard, aiohttp_client):
    server, emergency, _, _ = full_dashboard
    app = server.create_app()
    client = await aiohttp_client(app)

    await client.post("/api/emergency/pause")
    resp = await client.post("/api/emergency/resume")
    assert resp.status == 200
    assert emergency.is_paused is False


async def test_approval_rules_endpoint(full_dashboard, aiohttp_client):
    server, _, rule_store, _ = full_dashboard
    await rule_store.add_rule(ApprovalRule(match_skill="file.*", decision="allow"))

    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/approvals/rules")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 1


async def test_trust_records_endpoint(full_dashboard, aiohttp_client):
    server, _, _, trust = full_dashboard
    await trust.record_outcome("file.read", success=True)

    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/trust/records")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) >= 1


async def test_config_endpoint(full_dashboard, aiohttp_client):
    server, _, _, _ = full_dashboard
    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/config")
    assert resp.status == 200
    data = await resp.json()
    assert "autonomy_level" in data


async def test_connectors_endpoint(full_dashboard, aiohttp_client):
    server, _, _, _ = full_dashboard
    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/connectors")
    assert resp.status == 200
    data = await resp.json()
    assert isinstance(data, list)
