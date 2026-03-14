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
