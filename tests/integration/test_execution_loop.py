# tests/integration/test_execution_loop.py
from pathlib import Path

import pytest

from atlas.control.approval import ApprovalWorkflow
from atlas.control.audit import AuditLogger
from atlas.control.policy import PolicyEngine
from atlas.contracts.types import AutonomyLevel
from atlas.core.loop import ExecutionLoop
from atlas.core.missions import Mission
from atlas.core.tasks import Task
from atlas.env.facade import EnvironmentFacade
from atlas.env.filesystem import FilesystemProvider
from atlas.env.process import ProcessProvider
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.store import DatabaseStore
from atlas.memory.working import WorkingMemoryStore
from atlas.skills.registry import SkillRegistry
from atlas.skills.runtime import InvocationRuntime
from atlas.skills.seed import register_seed_skills


@pytest.fixture
async def loop(tmp_path: Path, tmp_workspace: Path):
    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()

    fs = FilesystemProvider(workspace=str(tmp_workspace))
    proc = ProcessProvider()
    env = EnvironmentFacade(filesystem=fs, process=proc, claude=None)

    registry = SkillRegistry()
    register_seed_skills(registry, fs, proc)
    runtime = InvocationRuntime(registry)

    policy = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
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
    yield loop
    await audit.close()
    await db.close()


async def test_execute_file_read_task(loop: ExecutionLoop, tmp_workspace: Path):
    mission = Mission(goal_text="read a file")
    task = Task(
        description="Read main.py",
        skill_id="file.read",
        input_params={"path": str(tmp_workspace / "src" / "main.py")},
    )
    mission.tasks = [task]

    result = await loop.execute_mission(mission)
    assert result.status.value == "completed"
    assert len(result.tasks) == 1
    assert result.tasks[0].status.value == "completed"
    assert "hello" in result.tasks[0].result["content"]


async def test_execute_multiple_tasks(loop: ExecutionLoop, tmp_workspace: Path):
    mission = Mission(goal_text="read and search")
    mission.tasks = [
        Task(
            description="Read main.py",
            skill_id="file.read",
            input_params={"path": str(tmp_workspace / "src" / "main.py")},
        ),
        Task(
            description="Search for Python files",
            skill_id="file.search",
            input_params={"root": str(tmp_workspace), "pattern": "**/*.py"},
        ),
    ]

    result = await loop.execute_mission(mission)
    assert result.status.value == "completed"
    assert all(t.status.value == "completed" for t in result.tasks)


async def test_execute_records_episode(loop: ExecutionLoop, tmp_workspace: Path):
    mission = Mission(goal_text="test episode recording")
    mission.tasks = [
        Task(
            description="Read main.py",
            skill_id="file.read",
            input_params={"path": str(tmp_workspace / "src" / "main.py")},
        ),
    ]
    await loop.execute_mission(mission)

    episodes = await loop._episodic.query_recent(limit=1)
    assert len(episodes) == 1
    assert "test episode recording" in episodes[0].trigger
