"""Dashboard API — HTTP REST endpoints for monitoring and control."""
import json
import logging
import time
from typing import Any, Callable, Coroutine

from aiohttp import web

from atlas.config import AtlasConfig
from atlas.control.audit import AuditLogger
from atlas.control.emergency import EmergencyController
from atlas.control.approval_rules import ApprovalRuleStore
from atlas.control.trust import TrustTracker
from atlas.memory.store import DatabaseStore
from atlas.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

GoalHandler = Callable[[str], Coroutine[Any, Any, dict]]


class DashboardServer:
    """REST API for monitoring and controlling ATLAS state."""

    def __init__(
        self,
        db: DatabaseStore,
        audit: AuditLogger,
        registry: SkillRegistry,
        goal_handler: GoalHandler | None = None,
        config: AtlasConfig | None = None,
        emergency_controller: EmergencyController | None = None,
        approval_rule_store: ApprovalRuleStore | None = None,
        trust_tracker: TrustTracker | None = None,
    ):
        self._db = db
        self._audit = audit
        self._registry = registry
        self._goal_handler = goal_handler
        self._config = config
        self._emergency = emergency_controller
        self._rule_store = approval_rule_store
        self._trust = trust_tracker
        self._start_time = time.monotonic()

    def create_app(self) -> web.Application:
        app = web.Application()
        # Existing
        app.router.add_get("/api/status", self._handle_status)
        app.router.add_get("/api/missions", self._handle_missions)
        app.router.add_get("/api/skills", self._handle_skills)
        app.router.add_get("/api/memory/stats", self._handle_memory_stats)
        app.router.add_get("/api/audit", self._handle_audit)
        app.router.add_post("/api/goal", self._handle_goal)
        # Slice 1: Emergency
        app.router.add_post("/api/emergency/pause", self._handle_pause)
        app.router.add_post("/api/emergency/resume", self._handle_resume)
        app.router.add_post("/api/emergency/kill", self._handle_kill)
        # Slice 2: Approval rules
        app.router.add_get("/api/approvals/rules", self._handle_list_rules)
        app.router.add_post("/api/approvals/rules", self._handle_add_rule)
        app.router.add_delete("/api/approvals/rules/{rule_id}", self._handle_remove_rule)
        # Slice 3: Trust
        app.router.add_get("/api/trust/recommendations", self._handle_trust_recommendations)
        app.router.add_post("/api/trust/recommendations/{id}/accept", self._handle_trust_accept)
        app.router.add_post("/api/trust/recommendations/{id}/dismiss", self._handle_trust_dismiss)
        app.router.add_get("/api/trust/records", self._handle_trust_records)
        # Slice 4: Remaining
        app.router.add_get("/api/tasks", self._handle_tasks)
        app.router.add_get("/api/health", self._handle_health)
        app.router.add_get("/api/config", self._handle_config)
        app.router.add_get("/api/connectors", self._handle_connectors)
        return app

    # --- Existing endpoints ---

    async def _handle_status(self, request: web.Request) -> web.Response:
        uptime = time.monotonic() - self._start_time
        payload = {
            "status": "running",
            "uptime_seconds": round(uptime, 1),
            "paused": self._emergency.is_paused if self._emergency else False,
            "active_task_id": self._emergency.active_task_id if self._emergency else None,
        }
        if self._rule_store:
            rules = await self._rule_store.list_rules()
            payload["standing_rules_count"] = len(rules)
        return web.json_response(payload)

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
                "skill_id": s.skill_id, "name": s.name, "description": s.description,
                "risk_level": s.risk_level.value, "tags": s.tags,
            }
            for s in skills
        ]
        return web.json_response(data)

    async def _handle_memory_stats(self, request: web.Request) -> web.Response:
        episode_cursor = await self._db.db.execute("SELECT COUNT(*) FROM episodes")
        episode_count = (await episode_cursor.fetchone())[0]
        mission_cursor = await self._db.db.execute("SELECT COUNT(*) FROM missions")
        mission_count = (await mission_cursor.fetchone())[0]
        embedding_cursor = await self._db.db.execute("SELECT COUNT(*) FROM episode_embeddings")
        embedding_count = (await embedding_cursor.fetchone())[0]
        return web.json_response({
            "episode_count": episode_count,
            "mission_count": mission_count,
            "embedding_count": embedding_count,
        })

    async def _handle_audit(self, request: web.Request) -> web.Response:
        limit = int(request.query.get("limit", "50"))
        entries = await self._audit.query(limit=limit)
        return web.json_response(entries)

    async def _handle_goal(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"status": "error", "message": "invalid JSON"}, status=400)
        goal_text = body.get("goal_text")
        if not goal_text:
            return web.json_response({"status": "error", "message": "goal_text is required"}, status=400)
        if not self._goal_handler:
            return web.json_response({"status": "error", "message": "no goal handler configured"}, status=500)
        result = await self._goal_handler(goal_text)
        return web.json_response(result)

    # --- Slice 1: Emergency endpoints ---

    async def _handle_pause(self, request: web.Request) -> web.Response:
        if not self._emergency:
            return web.json_response({"error": "emergency controls not configured"}, status=501)
        self._emergency.pause()
        return web.json_response({"status": "paused"})

    async def _handle_resume(self, request: web.Request) -> web.Response:
        if not self._emergency:
            return web.json_response({"error": "emergency controls not configured"}, status=501)
        self._emergency.resume()
        return web.json_response({"status": "resumed"})

    async def _handle_kill(self, request: web.Request) -> web.Response:
        if not self._emergency:
            return web.json_response({"error": "emergency controls not configured"}, status=501)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)
        task_id = body.get("task_id", "")
        killed = self._emergency.kill_task(task_id)
        return web.json_response({"killed": killed})

    # --- Slice 2: Approval rule endpoints ---

    async def _handle_list_rules(self, request: web.Request) -> web.Response:
        if not self._rule_store:
            return web.json_response({"error": "approval rules not configured"}, status=501)
        rules = await self._rule_store.list_rules()
        data = [
            {
                "rule_id": r.rule_id, "rule_type": r.rule_type,
                "match_skill": r.match_skill, "match_risk": r.match_risk,
                "match_path": r.match_path, "decision": r.decision,
                "created_at": r.created_at, "expires_at": r.expires_at,
                "description": r.description,
            }
            for r in rules
        ]
        return web.json_response(data)

    async def _handle_add_rule(self, request: web.Request) -> web.Response:
        if not self._rule_store:
            return web.json_response({"error": "approval rules not configured"}, status=501)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)
        from atlas.contracts.types import ApprovalRule
        rule = ApprovalRule(
            match_skill=body.get("match_skill", "*"),
            match_risk=body.get("match_risk", "*"),
            match_path=body.get("match_path"),
            decision=body.get("decision", "allow"),
            description=body.get("description", ""),
        )
        rule_id = await self._rule_store.add_rule(rule)
        return web.json_response({"rule_id": rule_id})

    async def _handle_remove_rule(self, request: web.Request) -> web.Response:
        if not self._rule_store:
            return web.json_response({"error": "approval rules not configured"}, status=501)
        rule_id = request.match_info["rule_id"]
        removed = await self._rule_store.remove_rule(rule_id)
        if not removed:
            return web.json_response({"error": "rule not found"}, status=404)
        return web.json_response({"status": "removed"})

    # --- Slice 3: Trust endpoints ---

    async def _handle_trust_recommendations(self, request: web.Request) -> web.Response:
        if not self._trust:
            return web.json_response({"error": "trust tracker not configured"}, status=501)
        status_filter = request.query.get("status", "pending")
        recs = await self._trust.list_recommendations(status=status_filter)
        data = [
            {
                "recommendation_id": r.recommendation_id, "skill_id": r.skill_id,
                "current_level": r.current_level, "recommended_level": r.recommended_level,
                "direction": r.direction, "evidence": r.evidence,
                "status": r.status, "mission_id": r.mission_id,
                "created_at": r.created_at, "resolved_at": r.resolved_at,
            }
            for r in recs
        ]
        return web.json_response(data)

    async def _handle_trust_accept(self, request: web.Request) -> web.Response:
        if not self._trust:
            return web.json_response({"error": "trust tracker not configured"}, status=501)
        rec_id = request.match_info["id"]
        await self._trust.resolve_recommendation(rec_id, accepted=True)
        return web.json_response({"status": "accepted"})

    async def _handle_trust_dismiss(self, request: web.Request) -> web.Response:
        if not self._trust:
            return web.json_response({"error": "trust tracker not configured"}, status=501)
        rec_id = request.match_info["id"]
        await self._trust.resolve_recommendation(rec_id, accepted=False)
        return web.json_response({"status": "dismissed"})

    async def _handle_trust_records(self, request: web.Request) -> web.Response:
        cursor = await self._db.db.execute(
            "SELECT skill_id, successes, failures, consecutive_successes, "
            "total_invocations, autonomy_override, last_outcome, updated_at "
            "FROM trust_records ORDER BY skill_id"
        )
        rows = await cursor.fetchall()
        data = [
            {
                "skill_id": r[0], "successes": r[1], "failures": r[2],
                "consecutive_successes": r[3], "total_invocations": r[4],
                "autonomy_override": r[5], "last_outcome": r[6], "updated_at": r[7],
            }
            for r in rows
        ]
        return web.json_response(data)

    # --- Slice 4: Remaining endpoints ---

    async def _handle_tasks(self, request: web.Request) -> web.Response:
        mission_id = request.query.get("mission_id")
        if mission_id:
            cursor = await self._db.db.execute(
                "SELECT task_id, mission_id, description, skill_id, status, result "
                "FROM tasks WHERE mission_id = ? ORDER BY created_at",
                (mission_id,),
            )
        else:
            cursor = await self._db.db.execute(
                "SELECT task_id, mission_id, description, skill_id, status, result "
                "FROM tasks ORDER BY created_at DESC LIMIT 50"
            )
        rows = await cursor.fetchall()
        data = [
            {
                "task_id": r[0], "mission_id": r[1], "description": r[2],
                "skill_id": r[3], "status": r[4], "result": r[5],
            }
            for r in rows
        ]
        return web.json_response(data)

    async def _handle_health(self, request: web.Request) -> web.Response:
        health = {}
        # Database
        try:
            await self._db.db.execute("SELECT 1")
            health["database"] = "ok"
        except Exception as e:
            health["database"] = f"error: {e}"
        # Skill registry
        try:
            count = len(self._registry.list_all())
            health["skill_registry"] = f"ok ({count} skills)"
        except Exception as e:
            health["skill_registry"] = f"error: {e}"
        # Memory
        try:
            cursor = await self._db.db.execute("SELECT COUNT(*) FROM episodes")
            count = (await cursor.fetchone())[0]
            health["memory"] = f"ok ({count} episodes)"
        except Exception as e:
            health["memory"] = f"error: {e}"
        # Emergency
        if self._emergency:
            health["emergency"] = "paused" if self._emergency.is_paused else "ok"
        else:
            health["emergency"] = "not_configured"
        return web.json_response(health)

    async def _handle_config(self, request: web.Request) -> web.Response:
        if not self._config:
            return web.json_response({"error": "config not available"}, status=501)
        # Return non-sensitive config
        data = {
            "autonomy_level": self._config.control.autonomy_level,
            "log_level": self._config.log_level,
            "episode_retention_days": self._config.memory.episode_retention_days,
            "context_token_budget": self._config.memory.context_default_token_budget,
            "vector_search_enabled": self._config.memory.vector_search.enabled,
            "forge_enabled": self._config.skills.forge_enabled,
            "seed_skills": self._config.skills.seed_skills,
            "trust_escalation_threshold": self._config.trust.escalation_threshold,
            "trust_demotion_failure_count": self._config.trust.demotion_failure_count,
            "observation_watches": self._config.observation.watches,
            "reactive_enabled": self._config.reactive.enabled,
            "mcp_enabled": self._config.mcp.enabled,
            "webhook_enabled": self._config.webhook.enabled,
        }
        return web.json_response(data)

    async def _handle_connectors(self, request: web.Request) -> web.Response:
        connectors = []
        if self._config and self._config.github.token:
            connectors.append({
                "name": "github",
                "status": "configured",
                "owner": self._config.github.owner,
                "repo": self._config.github.repo,
            })
        return web.json_response(connectors)
