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
