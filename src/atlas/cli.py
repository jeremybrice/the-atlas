"""ATLAS CLI — command-line interface for the agent."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click

from atlas.contracts.types import AutonomyLevel
from atlas.control.approval import ApprovalWorkflow
from atlas.control.audit import AuditLogger
from atlas.control.policy import PolicyEngine
from atlas.core.loop import ExecutionLoop
from atlas.core.missions import Mission, parse_task_plan, PLANNING_PROMPT_TEMPLATE
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


def _ensure_data_dir() -> Path:
    data_dir = Path.home() / ".atlas"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "config").mkdir(exist_ok=True)
    (data_dir / "data").mkdir(exist_ok=True)
    (data_dir / "logs").mkdir(exist_ok=True)
    return data_dir


def _setup_logging(data_dir: Path, level: str = "INFO") -> None:
    log_file = data_dir / "logs" / "atlas.log"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format='{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stderr),
        ],
    )


@click.group()
def main():
    """ATLAS — Autonomous Tool-Learning Agent System"""
    pass


@main.command()
@click.argument("goal_text")
@click.option("--autonomy", type=click.Choice(["observe", "suggest", "act"]), default="act",
              help="Autonomy level")
@click.option("--auto-approve", is_flag=True, help="Auto-approve all actions (for testing)")
def goal(goal_text: str, autonomy: str, auto_approve: bool):
    """Submit a goal for ATLAS to accomplish."""
    asyncio.run(_run_goal(goal_text, autonomy, auto_approve))


async def _run_goal(goal_text: str, autonomy: str, auto_approve: bool) -> None:
    data_dir = _ensure_data_dir()
    _setup_logging(data_dir)

    # Map CLI autonomy flag
    autonomy_map = {
        "observe": AutonomyLevel.OBSERVE,
        "suggest": AutonomyLevel.SUGGEST,
        "act": AutonomyLevel.ACT_WITHIN_BOUNDS,
    }
    autonomy_level = autonomy_map[autonomy]

    # Initialize components
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()

    fs = FilesystemProvider(workspace=str(Path.cwd()))
    proc = ProcessProvider()
    claude = ClaudeCodeBridge()
    env = EnvironmentFacade(filesystem=fs, process=proc, claude=claude)

    registry = SkillRegistry()
    register_seed_skills(registry, fs, proc)
    runtime = InvocationRuntime(registry)

    policy = PolicyEngine(autonomy_level=autonomy_level)
    audit = AuditLogger(db=db.db)
    await audit.initialize()
    approval = ApprovalWorkflow(auto_approve=auto_approve)

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

    try:
        # Plan the mission
        click.echo(f"[planning] Decomposing goal: {goal_text}")

        skills_desc = "\n".join(
            f"- {s.skill_id}: {s.description}" for s in registry.list_all()
        )
        env_state = str(env.get_state())

        prompt = PLANNING_PROMPT_TEMPLATE.format(
            goal=goal_text, skills=skills_desc, env_state=env_state
        )

        try:
            response = await env.claude_oneshot(prompt)
            tasks = parse_task_plan(response.content)
        except Exception as e:
            click.echo(f"[error] Planning failed: {e}", err=True)
            sys.exit(1)

        if not tasks:
            click.echo("[error] Could not parse a task plan from Claude's response.", err=True)
            click.echo(f"[debug] Raw response ({len(response.content)} chars):", err=True)
            click.echo(repr(response.content[:500]), err=True)
            sys.exit(1)

        mission = Mission(goal_text=goal_text, tasks=tasks)
        click.echo(f"[planned] {len(tasks)} tasks")

        # Execute
        result = await loop.execute_mission(mission)

        # Report
        completed = sum(1 for t in result.tasks if t.status.value == "completed")
        total = len(result.tasks)
        if result.status.value == "completed":
            click.echo(f"[complete] {completed}/{total} tasks succeeded. Episode recorded.")
        else:
            click.echo(f"[failed] {completed}/{total} tasks succeeded. Mission failed.", err=True)
            for t in result.tasks:
                if t.error:
                    click.echo(f"  - {t.description}: {t.error}", err=True)
    finally:
        await db.close()


@main.command()
def status():
    """Show ATLAS status."""
    click.echo("ATLAS is not running as a daemon. Use 'atlas goal' to execute tasks.")


if __name__ == "__main__":
    main()
