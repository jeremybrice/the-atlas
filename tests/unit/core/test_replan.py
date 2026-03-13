# tests/unit/core/test_replan.py
from unittest.mock import AsyncMock

from atlas.contracts.types import AutonomyLevel, ClaudeResponse
from atlas.control.approval import ApprovalWorkflow
from atlas.control.audit import AuditLogger
from atlas.control.policy import PolicyEngine
from atlas.core.loop import ExecutionLoop, build_replan_prompt
from atlas.core.missions import Mission
from atlas.core.tasks import Task
from atlas.env.claude import ClaudeCodeBridge
from atlas.env.facade import EnvironmentFacade
from atlas.env.filesystem import FilesystemProvider
from atlas.env.process import ProcessProvider
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.store import DatabaseStore
from atlas.memory.working import WorkingMemoryStore
from atlas.skills.registry import SkillRegistry
from atlas.skills.runtime import InvocationRuntime
from atlas.skills.seed import register_seed_skills


def test_replan_prompt_includes_error():
    prompt = build_replan_prompt(
        original_goal="add CI workflow",
        failed_task_desc="Read package.json",
        error="File not found: package.json",
        remaining_tasks=["Write CI config", "Commit changes"],
        skills="file.read, file.write, shell.execute",
        context="python project with pyproject.toml",
    )
    assert "package.json" in prompt
    assert "File not found" in prompt
    assert "add CI workflow" in prompt
    assert "pyproject.toml" in prompt


def test_replan_prompt_includes_remaining():
    prompt = build_replan_prompt(
        original_goal="test",
        failed_task_desc="step 2",
        error="oops",
        remaining_tasks=["step 3", "step 4"],
        skills="file.read",
        context="",
    )
    assert "step 3" in prompt
    assert "step 4" in prompt


async def test_replan_called_on_task_failure(tmp_path):
    """When a task fails, the loop should attempt replanning via Claude."""

    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()

    fs = FilesystemProvider(workspace=str(tmp_path))
    proc = ProcessProvider()

    mock_claude = AsyncMock(spec=ClaudeCodeBridge)
    mock_claude.oneshot = AsyncMock(return_value=ClaudeResponse(
        content='{"tasks": []}',
        parsed_output={"tasks": []},
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

    loop = ExecutionLoop(
        registry=registry,
        runtime=runtime,
        environment=env,
        policy=policy,
        audit=audit,
        approval=approval,
        working_memory=working,
        episodic_memory=episodic,
    )

    tasks = [
        Task(description="Read nonexistent file", skill_id="file.read",
             input_params={"path": str(tmp_path / "nonexistent.txt")}),
        Task(description="Write a file", skill_id="file.write",
             input_params={"path": str(tmp_path / "out.txt"), "content": "hello"}),
    ]
    mission = Mission(goal_text="test replanning", tasks=tasks)
    await loop.execute_mission(mission)

    assert mock_claude.oneshot.call_count >= 1

    await db.close()
