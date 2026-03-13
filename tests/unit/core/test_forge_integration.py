# tests/unit/core/test_forge_integration.py
from unittest.mock import AsyncMock, MagicMock
from atlas.core.loop import ExecutionLoop
from atlas.core.tasks import Task
from atlas.core.missions import Mission


async def test_execution_loop_triggers_forge_on_missing_skill(tmp_path):
    """When a task references a skill that doesn't exist, the loop should attempt forge."""
    from atlas.contracts.errors import SkillNotFoundError

    registry = MagicMock()
    registry.get.side_effect = SkillNotFoundError("Skill 'custom.deploy' not found")

    forge = AsyncMock()
    forge.create_skill = AsyncMock(return_value=MagicMock(success=False, error="forge disabled in test"))

    loop = ExecutionLoop(
        registry=registry,
        runtime=MagicMock(),
        environment=MagicMock(),
        policy=MagicMock(),
        audit=AsyncMock(),
        approval=AsyncMock(),
        working_memory=MagicMock(),
        episodic_memory=AsyncMock(),
        forge=forge,
    )

    task = Task(description="deploy the app", skill_id="custom.deploy")
    mission = Mission(goal_text="deploy", tasks=[task])
    await loop.execute_mission(mission)

    forge.create_skill.assert_called_once()
