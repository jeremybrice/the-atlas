"""Execution Loop — the central plan-act-observe-reflect cycle."""

from __future__ import annotations

import logging

from atlas.contracts.types import (
    ApprovalRequest,
    ApprovalResult,
    AuditEntry,
    ContextQuery,
    Episode,
    EpisodeType,
    ExecutionContext,
    MissionStatus,
    PolicyDecision,
    ProposedAction,
    TaskStatus,
)
from atlas.memory.retrieval import ContextAssembler
from atlas.control.approval import ApprovalWorkflow
from atlas.control.audit import AuditLogger
from atlas.control.policy import PolicyEngine
from atlas.core.missions import Mission, parse_task_plan, PLANNING_SYSTEM_PROMPT
from atlas.core.tasks import Task
from atlas.env.facade import EnvironmentFacade
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.working import WorkingMemoryStore
from atlas.skills.registry import SkillRegistry
from atlas.skills.runtime import InvocationRuntime

logger = logging.getLogger(__name__)


def build_replan_prompt(
    original_goal: str,
    failed_task_desc: str,
    error: str,
    remaining_tasks: list[str],
    skills: str,
    context: str,
) -> str:
    remaining = ", ".join(remaining_tasks) if remaining_tasks else "none"
    return (
        f"A task failed during execution. Replan the remaining work. "
        f"Original goal: {original_goal}. "
        f"Failed task: {failed_task_desc}. Error: {error}. "
        f"Remaining tasks that were planned: {remaining}. "
        f"Available skills: {skills}. Project context: {context}. "
        f'Respond with ONLY JSON: {{"tasks":[{{"description":"...","skill":"skill.id","params":{{}}}}]}}'
    )


class ExecutionLoop:
    """Sequentially executes a mission's tasks, checking permissions and logging."""

    def __init__(
        self,
        registry: SkillRegistry,
        runtime: InvocationRuntime,
        environment: EnvironmentFacade,
        policy: PolicyEngine,
        audit: AuditLogger,
        approval: ApprovalWorkflow,
        working_memory: WorkingMemoryStore,
        episodic_memory: EpisodicMemoryStore,
        forge=None,
        max_replans: int = 2,
        context_assembler: ContextAssembler | None = None,
        embedding_provider=None,
        vector_store=None,
        search_limit: int = 50,
        semantic_weight: float = 0.6,
        keyword_weight: float = 0.4,
        emergency_controller=None,
        trust_tracker=None,
        db=None,
    ):
        self._registry = registry
        self._runtime = runtime
        self._env = environment
        self._policy = policy
        self._audit = audit
        self._approval = approval
        self._working = working_memory
        self._episodic = episodic_memory
        self._forge = forge
        self._max_replans = max_replans
        self._context_assembler = context_assembler
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store
        self._search_limit = search_limit
        self._semantic_weight = semantic_weight
        self._keyword_weight = keyword_weight
        self._emergency = emergency_controller
        self._trust_tracker = trust_tracker
        self._trust_signals: list = []
        self._db = db

    async def execute_mission(self, mission: Mission) -> Mission:
        mission.status = MissionStatus.ACTIVE
        ctx = ExecutionContext.new(mission_id=mission.mission_id)
        actions_log: list[dict] = []
        replans_remaining = self._max_replans

        await self._persist_mission(mission)

        # Retrieve episodic context if assembler is available
        context_text = ""
        if self._context_assembler:
            try:
                query = ContextQuery(
                    purpose="planning",
                    task_description=mission.goal_text,
                    token_budget=4000,
                )

                if self._embedding_provider and self._vector_store:
                    # Hybrid path: combine keyword + semantic scores
                    keyword_results = await self._episodic.search_scored(
                        mission.goal_text,
                        limit=self._search_limit,
                    )
                    keyword_scores = dict(keyword_results)

                    query_embedding = await self._embedding_provider.embed_query(
                        mission.goal_text
                    )
                    if query_embedding is not None:
                        semantic_results = await self._vector_store.search(
                            query_embedding,
                            limit=self._search_limit,
                        )
                        semantic_scores = dict(semantic_results)
                    else:
                        semantic_scores = {}

                    merged = self._context_assembler.merge_scores(
                        keyword_scores,
                        semantic_scores,
                        semantic_weight=self._semantic_weight,
                        keyword_weight=self._keyword_weight,
                    )
                    all_ids = set(keyword_scores) | set(semantic_scores)
                    episodes_by_id = {}
                    for eid in all_ids:
                        ep = await self._episodic.get_by_id(eid)
                        if ep:
                            episodes_by_id[eid] = ep

                    bundle = self._context_assembler.assemble_ranked(
                        query, episodes_by_id, merged
                    )
                    logger.info(
                        "Assembled %d tokens of hybrid context (%d keyword, %d semantic)",
                        bundle.total_tokens,
                        len(keyword_scores),
                        len(semantic_scores),
                    )
                else:
                    # Fallback: recency-based retrieval
                    recent_episodes = await self._episodic.query_recent(limit=50)
                    bundle = self._context_assembler.assemble(query, recent_episodes)

                if bundle.contents:
                    context_text = "\n\n".join(c["text"] for c in bundle.contents)
            except Exception as e:
                logger.warning("Context assembly failed, proceeding without: %s", e)

        total = len(mission.tasks)
        i = 0
        while i < len(mission.tasks):
            task = mission.tasks[i]
            step_ctx = ExecutionContext(
                correlation_id=ctx.correlation_id,
                mission_id=mission.mission_id,
                task_id=task.task_id,
            )
            # Check emergency controls
            if self._emergency:
                await self._emergency.wait_if_paused()
                self._emergency.set_active_task(task.task_id)
                if self._emergency.is_task_cancelled(task.task_id):
                    task.status = TaskStatus.CANCELLED
                    task.error = "Cancelled by emergency control"
                    if self._emergency:
                        self._emergency.clear_active_task()
                    i += 1
                    continue

            logger.info("[task %d/%d] %s", i + 1, total, task.description)

            success = await self._execute_task(task, step_ctx)
            if self._emergency:
                self._emergency.clear_active_task()
            actions_log.append(
                {
                    "task_id": task.task_id,
                    "description": task.description,
                    "skill_id": task.skill_id,
                    "status": task.status.value,
                }
            )

            if not success and replans_remaining > 0:
                replans_remaining -= 1
                remaining_descs = [t.description for t in mission.tasks[i + 1 :]]
                skills_desc = ", ".join(s.skill_id for s in self._registry.list_all())
                replan_prompt = build_replan_prompt(
                    original_goal=mission.goal_text,
                    failed_task_desc=task.description,
                    error=task.error or "unknown",
                    remaining_tasks=remaining_descs,
                    skills=skills_desc,
                    context=context_text,
                )
                try:
                    response = await self._env.claude_oneshot(
                        replan_prompt,
                        system_prompt=PLANNING_SYSTEM_PROMPT,
                    )
                    new_tasks = parse_task_plan(response.content)
                    if new_tasks:
                        mission.tasks = mission.tasks[: i + 1] + new_tasks
                        total = len(mission.tasks)
                        logger.info(
                            "Replanned: %d new tasks after failure", len(new_tasks)
                        )
                except Exception as e:
                    logger.warning("Replanning failed: %s", e)
            elif not success:
                break

            i += 1

        all_succeeded = all(t.status == TaskStatus.COMPLETED for t in mission.tasks)
        mission.status = (
            MissionStatus.COMPLETED if all_succeeded else MissionStatus.FAILED
        )

        # Collect trust recommendations from signals gathered during execution
        trust_recommendations = []
        if self._trust_tracker and self._trust_signals:
            for signal in self._trust_signals:
                direction = "escalate" if signal.should_escalate else "demote"
                try:
                    rec = await self._trust_tracker.create_recommendation(
                        signal.skill_id,
                        direction,
                        mission_id=mission.mission_id,
                    )
                    trust_recommendations.append(rec)
                except Exception as e:
                    logger.warning("Failed to create trust recommendation: %s", e)
            self._trust_signals = []
        mission.trust_recommendations = trust_recommendations

        # Record episode
        await self._episodic.record(
            Episode(
                episode_type=EpisodeType.TASK_EXECUTION,
                trigger=mission.goal_text,
                plan="; ".join(t.description for t in mission.tasks),
                actions=actions_log,
                outcome=mission.status.value,
                mission_id=mission.mission_id,
                correlation_id=ctx.correlation_id,
            )
        )

        await self._persist_mission(mission)
        return mission

    async def _persist_mission(self, mission: Mission) -> None:
        """Write mission and its tasks to the database."""
        if not self._db:
            return
        try:
            import json
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).isoformat()
            await self._db.db.execute(
                "INSERT OR REPLACE INTO missions "
                "(mission_id, goal_text, status, task_list, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, COALESCE("
                "(SELECT created_at FROM missions WHERE mission_id = ?), ?), ?)",
                (
                    mission.mission_id,
                    mission.goal_text,
                    mission.status.value,
                    json.dumps([t.description for t in mission.tasks]),
                    mission.mission_id,
                    now,
                    now,
                ),
            )
            for task in mission.tasks:
                await self._db.db.execute(
                    "INSERT OR REPLACE INTO tasks "
                    "(task_id, mission_id, description, task_type, skill_id, "
                    "input_params, expected_outcome, status, result, priority, "
                    "retry_count, max_retries, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "COALESCE((SELECT created_at FROM tasks WHERE task_id = ?), ?))",
                    (
                        task.task_id,
                        mission.mission_id,
                        task.description,
                        "skill_invocation",
                        task.skill_id,
                        json.dumps(task.input_params),
                        task.expected_outcome,
                        task.status.value,
                        str(task.result) if task.result else None,
                        task.priority,
                        task.retry_count,
                        task.max_retries,
                        task.task_id,
                        now,
                    ),
                )
            await self._db.db.commit()
        except Exception as e:
            logger.warning("Failed to persist mission: %s", e)

    async def _execute_task(self, task: Task, ctx: ExecutionContext) -> bool:
        if not task.skill_id:
            task.status = TaskStatus.FAILED
            task.error = "No skill_id assigned to task"
            return False

        # Get skill info for risk assessment
        try:
            skill_desc = self._registry.get(task.skill_id)
        except Exception as e:
            # Attempt forge if available
            if self._forge:
                logger.info("Skill %s not found, attempting forge", task.skill_id)
                forge_result = await self._forge.create_skill(
                    gap_description=f"Need skill '{task.skill_id}' for: {task.description}",
                    context=task.description,
                )
                if forge_result.success:
                    try:
                        skill_desc = self._registry.get(forge_result.skill_id)
                        task.skill_id = forge_result.skill_id
                    except Exception:
                        task.status = TaskStatus.FAILED
                        task.error = f"Forged skill not found after creation: {forge_result.skill_id}"
                        return False
                else:
                    task.status = TaskStatus.FAILED
                    task.error = (
                        f"Skill not found and forge failed: {forge_result.error}"
                    )
                    return False
            else:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                return False

        # Check permission
        action = ProposedAction(
            action_type=f"skill_invoke:{task.skill_id}",
            domain="core",
            description=task.description,
            params=task.input_params,
            risk_level=skill_desc.risk_level,
            skill_id=task.skill_id,
        )
        decision = self._policy.evaluate(action)

        if decision == PolicyDecision.DENY:
            task.status = TaskStatus.FAILED
            task.error = "Permission denied by policy"
            await self._log_audit(task, ctx, decision, "denied")
            return False

        if decision == PolicyDecision.REQUIRE_APPROVAL:
            request = ApprovalRequest(
                action=action,
                reasoning=f"Task: {task.description}",
            )
            approval = await self._approval.request_approval(request)
            if approval != ApprovalResult.APPROVED:
                task.status = TaskStatus.FAILED
                task.error = "Approval denied by user"
                await self._log_audit(task, ctx, decision, "denied")
                return False

        # Execute skill
        task.status = TaskStatus.EXECUTING
        result = await self._runtime.invoke(task.skill_id, task.input_params, ctx)

        if result.status == "success":
            task.status = TaskStatus.COMPLETED
            task.result = result.output
            await self._log_audit(task, ctx, decision, "success")
            success = True
        else:
            task.status = TaskStatus.FAILED
            task.error = result.error
            await self._log_audit(task, ctx, decision, "failure")
            success = False

        # Record trust outcome
        if self._trust_tracker and task.skill_id:
            try:
                outcome = await self._trust_tracker.record_outcome(
                    task.skill_id,
                    success=success,
                    ctx=ctx,
                )
                if outcome.should_escalate or outcome.should_demote:
                    self._trust_signals.append(outcome)
            except Exception as e:
                logger.warning("Trust tracking failed: %s", e)

        return success

    async def _log_audit(
        self,
        task: Task,
        ctx: ExecutionContext,
        decision: PolicyDecision,
        outcome: str,
    ) -> None:
        await self._audit.log(
            AuditEntry(
                correlation_id=ctx.correlation_id,
                actor="core.execution_loop",
                action_type=f"skill_invoke:{task.skill_id}",
                action_details=task.input_params,
                policy_decision=decision,
                outcome=outcome,
                mission_id=ctx.mission_id,
                task_id=ctx.task_id,
            )
        )
