"""Execution Loop — the central plan-act-observe-reflect cycle."""

from __future__ import annotations

import logging

from atlas.contracts.types import (
    ApprovalRequest,
    ApprovalResult,
    AuditEntry,
    Episode,
    EpisodeType,
    ExecutionContext,
    MissionStatus,
    PolicyDecision,
    ProposedAction,
    TaskStatus,
)
from atlas.control.approval import ApprovalWorkflow
from atlas.control.audit import AuditLogger
from atlas.control.policy import PolicyEngine
from atlas.core.missions import Mission
from atlas.core.tasks import Task
from atlas.env.facade import EnvironmentFacade
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.working import WorkingMemoryStore
from atlas.skills.registry import SkillRegistry
from atlas.skills.runtime import InvocationRuntime

logger = logging.getLogger(__name__)


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
    ):
        self._registry = registry
        self._runtime = runtime
        self._env = environment
        self._policy = policy
        self._audit = audit
        self._approval = approval
        self._working = working_memory
        self._episodic = episodic_memory

    async def execute_mission(self, mission: Mission) -> Mission:
        mission.status = MissionStatus.ACTIVE
        ctx = ExecutionContext.new(mission_id=mission.mission_id)
        actions_log: list[dict] = []

        total = len(mission.tasks)
        for i, task in enumerate(mission.tasks):
            step_ctx = ExecutionContext(
                correlation_id=ctx.correlation_id,
                mission_id=mission.mission_id,
                task_id=task.task_id,
            )
            logger.info(f"[task {i+1}/{total}] {task.description}")

            success = await self._execute_task(task, step_ctx)
            actions_log.append({
                "task_id": task.task_id,
                "description": task.description,
                "skill_id": task.skill_id,
                "status": task.status.value,
            })

            if not success:
                mission.status = MissionStatus.FAILED
                break
        else:
            mission.status = MissionStatus.COMPLETED

        # Record episode
        await self._episodic.record(Episode(
            episode_type=EpisodeType.TASK_EXECUTION,
            trigger=mission.goal_text,
            plan="; ".join(t.description for t in mission.tasks),
            actions=actions_log,
            outcome=mission.status.value,
            mission_id=mission.mission_id,
            correlation_id=ctx.correlation_id,
        ))

        return mission

    async def _execute_task(self, task: Task, ctx: ExecutionContext) -> bool:
        if not task.skill_id:
            task.status = TaskStatus.FAILED
            task.error = "No skill_id assigned to task"
            return False

        # Get skill info for risk assessment
        try:
            skill_desc = self._registry.get(task.skill_id)
        except Exception as e:
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
            return True
        else:
            task.status = TaskStatus.FAILED
            task.error = result.error
            await self._log_audit(task, ctx, decision, "failure")
            return False

    async def _log_audit(
        self, task: Task, ctx: ExecutionContext,
        decision: PolicyDecision, outcome: str,
    ) -> None:
        await self._audit.log(AuditEntry(
            correlation_id=ctx.correlation_id,
            actor="core.execution_loop",
            action_type=f"skill_invoke:{task.skill_id}",
            action_details=task.input_params,
            policy_decision=decision,
            outcome=outcome,
            mission_id=ctx.mission_id,
            task_id=ctx.task_id,
        ))
