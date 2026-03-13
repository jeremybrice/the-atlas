# tests/unit/core/test_forge_integration.py
"""Integration test: Forge is triggered when execution loop encounters missing skill."""

from unittest.mock import AsyncMock

from atlas.contracts.types import AutonomyLevel, ClaudeResponse
from atlas.control.approval import ApprovalWorkflow
from atlas.control.audit import AuditLogger
from atlas.control.policy import PolicyEngine
from atlas.core.loop import ExecutionLoop
from atlas.core.missions import Mission
from atlas.core.tasks import Task
from atlas.env.claude import ClaudeCodeBridge
from atlas.env.facade import EnvironmentFacade
from atlas.env.filesystem import FilesystemProvider
from atlas.env.process import ProcessProvider
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.store import DatabaseStore
from atlas.memory.working import WorkingMemoryStore
from atlas.skills.forge import SkillForge
from atlas.skills.registry import SkillRegistry
from atlas.skills.runtime import InvocationRuntime
from atlas.skills.seed import register_seed_skills


async def test_execution_loop_triggers_forge_on_missing_skill(tmp_path):
    """When a task references a skill that doesn't exist, the loop should attempt forge."""
    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()

    fs = FilesystemProvider(workspace=str(tmp_path))
    proc = ProcessProvider()

    # Mock only the Claude bridge
    mock_claude = AsyncMock(spec=ClaudeCodeBridge)
    mock_claude.oneshot = AsyncMock(return_value=ClaudeResponse(
        content="not valid skill code",
        parsed_output=None,
    ))

    env = EnvironmentFacade(filesystem=fs, process=proc, claude=mock_claude)
    registry = SkillRegistry()
    register_seed_skills(registry, fs, proc)
    runtime = InvocationRuntime(registry)

    policy = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    audit = AuditLogger(db=db.db)
    await audit.initialize()
    approval = ApprovalWorkflow(auto_approve=True)
    working = WorkingMemoryStore()
    episodic = EpisodicMemoryStore(db)

    forge = SkillForge(
        registry=registry,
        claude_bridge=mock_claude,
        skills_dir=str(tmp_path / "skills"),
        workspace=str(tmp_path),
        max_retries=0,
    )

    loop = ExecutionLoop(
        registry=registry,
        runtime=runtime,
        environment=env,
        policy=policy,
        audit=audit,
        approval=approval,
        working_memory=working,
        episodic_memory=episodic,
        forge=forge,
    )

    task = Task(description="deploy the app", skill_id="custom.deploy")
    mission = Mission(goal_text="deploy", tasks=[task])
    result = await loop.execute_mission(mission)

    # Forge should have been called (Claude bridge invoked for skill generation)
    assert mock_claude.oneshot.call_count >= 1

    # Task should have failed (mock Claude didn't return valid skill code)
    assert task.error is not None
    assert "forge failed" in task.error.lower() or "not found" in task.error.lower()

    await db.close()
