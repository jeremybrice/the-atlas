from unittest.mock import AsyncMock, MagicMock

import pytest

from atlas.contracts.types import (
    ClaudeResponse,
    ContextBundle,
    MissionStatus,
    PolicyDecision,
    SkillDescriptor,
    SkillResult,
)
from atlas.core.loop import ExecutionLoop
from atlas.core.missions import Mission
from atlas.core.tasks import Task
from atlas.memory.retrieval import ContextAssembler


@pytest.fixture
def mock_components():
    registry = MagicMock()
    registry.list_all.return_value = []
    registry.get.return_value = SkillDescriptor(
        skill_id="shell.execute", name="shell.execute", description="run shell"
    )

    runtime = MagicMock()
    runtime.invoke = AsyncMock(
        return_value=SkillResult(status="success", output="done")
    )

    env = MagicMock()
    env.claude_oneshot = AsyncMock(return_value=ClaudeResponse(content='{"tasks":[]}'))

    policy = MagicMock()
    policy.evaluate.return_value = PolicyDecision.ALLOW

    audit = MagicMock()
    audit.log = AsyncMock()

    approval = MagicMock()
    working = MagicMock()

    episodic = MagicMock()
    episodic.record = AsyncMock(return_value="ep-1")
    episodic.query_recent = AsyncMock(return_value=[])

    return registry, runtime, env, policy, audit, approval, working, episodic


async def test_execution_loop_calls_context_assembler(mock_components):
    """When context_assembler is provided, it should be called before task execution."""
    registry, runtime, env, policy, audit, approval, working, episodic = mock_components

    assembler = MagicMock(spec=ContextAssembler)
    assembler.assemble.return_value = ContextBundle(
        contents=[
            {
                "source": "past-episode",
                "text": "relevant context",
                "tokens": 10,
                "truncated": False,
            }
        ],
        total_tokens=10,
        budget_tokens=4000,
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
        context_assembler=assembler,
    )

    task = Task(
        description="run tests",
        skill_id="shell.execute",
        input_params={"command": "pytest"},
    )
    mission = Mission(goal_text="test the project", tasks=[task])

    await loop.execute_mission(mission)
    assert assembler.assemble.called


async def test_execution_loop_works_without_assembler(mock_components):
    """ExecutionLoop should work without a context_assembler (backward compatible)."""
    registry, runtime, env, policy, audit, approval, working, episodic = mock_components

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

    task = Task(
        description="run tests",
        skill_id="shell.execute",
        input_params={"command": "pytest"},
    )
    mission = Mission(goal_text="test the project", tasks=[task])

    result = await loop.execute_mission(mission)
    assert result.status == MissionStatus.COMPLETED
