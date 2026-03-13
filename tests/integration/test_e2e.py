"""End-to-end test: full goal execution with mocked Claude Code Bridge."""

import json
from pathlib import Path

import pytest

from atlas.contracts.types import AutonomyLevel
from atlas.control.approval import ApprovalWorkflow
from atlas.control.audit import AuditLogger
from atlas.control.policy import PolicyEngine
from atlas.core.loop import ExecutionLoop
from atlas.core.missions import Mission, parse_task_plan
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
async def e2e_env(tmp_path: Path, tmp_workspace: Path):
    """Full ATLAS environment with mocked Claude."""
    # Write a file to read in the workspace
    (tmp_workspace / "src" / "app.py").write_text(
        "def greet():\n    print('hello world')\n"
    )

    db = DatabaseStore(str(tmp_path / "e2e.db"))
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

    yield {
        "loop": loop,
        "workspace": tmp_workspace,
        "db": db,
        "audit": audit,
        "episodic": episodic,
    }

    await audit.close()
    await db.close()


async def test_full_goal_execution(e2e_env: dict):
    """Simulate: user submits goal, Claude returns plan, ATLAS executes it."""
    workspace = e2e_env["workspace"]
    loop = e2e_env["loop"]

    # Simulate Claude's planning response
    plan_json = json.dumps({
        "tasks": [
            {
                "description": "Read the application source",
                "skill": "file.read",
                "params": {"path": str(workspace / "src" / "app.py")},
            },
            {
                "description": "Write updated file with logging",
                "skill": "file.write",
                "params": {
                    "path": str(workspace / "src" / "app.py"),
                    "content": "import logging\n\ndef greet():\n    logging.info('hello world')\n",
                },
            },
        ]
    })

    tasks = parse_task_plan(plan_json)
    mission = Mission(goal_text="Add logging to app.py", tasks=tasks)

    result = await loop.execute_mission(mission)

    # Verify mission completed
    assert result.status.value == "completed"
    assert all(t.status.value == "completed" for t in result.tasks)

    # Verify file was actually modified
    content = (workspace / "src" / "app.py").read_text()
    assert "import logging" in content

    # Verify episode was recorded
    episodes = await e2e_env["episodic"].query_recent(limit=1)
    assert len(episodes) == 1
    assert "Add logging" in episodes[0].trigger

    # Verify audit entries were created
    audit_entries = await e2e_env["audit"].query(limit=10)
    assert len(audit_entries) >= 2  # one per task
