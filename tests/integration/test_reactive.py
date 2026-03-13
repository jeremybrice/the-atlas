import asyncio
from atlas.observation.engine import ObservationEngine
from atlas.observation.router import EventRouter, ReactiveRule
from atlas.contracts.types import EventType


async def test_file_change_triggers_goal(tmp_path):
    goals_received: list[str] = []

    async def goal_handler(goal_text: str) -> dict:
        goals_received.append(goal_text)
        return {"status": "completed"}

    rule = ReactiveRule(
        name="test-on-change",
        event_type=EventType.FILESYSTEM,
        source_pattern="*.py",
        goal_template="Run tests for {path}",
        cooldown_seconds=0,
    )
    router = EventRouter(rules=[rule])
    engine = ObservationEngine(router=router, goal_handler=goal_handler)

    engine.add_filesystem_watch(str(tmp_path), ["*.py"], debounce_seconds=0.1)
    await engine.start()
    try:
        (tmp_path / "app.py").write_text("x = 1")
        await asyncio.sleep(0.5)
        assert len(goals_received) >= 1
        assert "app.py" in goals_received[0]
    finally:
        await engine.stop()
