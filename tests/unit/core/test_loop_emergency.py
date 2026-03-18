import asyncio
import pytest
from unittest.mock import MagicMock
from atlas.control.audit import AuditLogger
from atlas.control.emergency import EmergencyController
from atlas.control.approval import ApprovalWorkflow
from atlas.control.policy import PolicyEngine
from atlas.core.loop import ExecutionLoop
from atlas.core.missions import Mission
from atlas.core.tasks import Task
from atlas.contracts.types import (
    AutonomyLevel, TaskStatus,
)
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.working import WorkingMemoryStore
from atlas.skills.registry import SkillRegistry
from atlas.skills.runtime import InvocationRuntime


@pytest.fixture
async def db(tmp_path):
    from atlas.memory.store import DatabaseStore
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def components(db):
    registry = SkillRegistry()

    async def noop_handler(params):
        return {"output": "done"}

    registry.register("file.read", "File Read", "Reads files", noop_handler, "low")

    runtime = InvocationRuntime(registry)
    env = MagicMock()
    policy = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    audit = AuditLogger(db=db.db)
    await audit.initialize()
    approval = ApprovalWorkflow(auto_approve=True)
    working = WorkingMemoryStore()
    episodic = EpisodicMemoryStore(db)

    return {
        "registry": registry,
        "runtime": runtime,
        "environment": env,
        "policy": policy,
        "audit": audit,
        "approval": approval,
        "working_memory": working,
        "episodic_memory": episodic,
    }


async def test_execution_loop_pauses_between_tasks(components):
    emergency = EmergencyController()
    loop = ExecutionLoop(**components, emergency_controller=emergency)

    # Pause before execution starts
    emergency.pause()

    task = Task(description="read a file", skill_id="file.read", input_params={"path": "test.txt"})
    mission = Mission(goal_text="test", tasks=[task])

    # Mission should not complete while paused
    exec_task = asyncio.create_task(loop.execute_mission(mission))

    await asyncio.sleep(0.2)
    assert not exec_task.done()

    # Resume — mission should complete
    emergency.resume()
    result = await asyncio.wait_for(exec_task, timeout=2.0)
    assert result.status.value == "completed"


async def test_execution_loop_kill_cancels_task(components):
    emergency = EmergencyController()
    loop = ExecutionLoop(**components, emergency_controller=emergency)

    task = Task(description="read a file", skill_id="file.read", input_params={"path": "test.txt"})

    # Pre-mark as active and kill so the cancelled set is populated
    emergency.set_active_task(task.task_id)
    emergency.kill_task(task.task_id)
    emergency.clear_active_task()

    mission = Mission(goal_text="test", tasks=[task])
    await loop.execute_mission(mission)  # result unused — only checking task status
    # Task should be cancelled since we killed it before execution
    assert task.status == TaskStatus.CANCELLED
