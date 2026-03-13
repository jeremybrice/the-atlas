from atlas.observation.router import EventRouter, ReactiveRule
from atlas.contracts.types import ObservationEvent, EventType


def test_router_matches_filesystem_event():
    rule = ReactiveRule(
        name="test-on-change",
        event_type=EventType.FILESYSTEM,
        source_pattern="*.py",
        goal_template="Run tests for {path}",
        cooldown_seconds=0,
    )
    router = EventRouter(rules=[rule])
    event = ObservationEvent(
        event_type=EventType.FILESYSTEM,
        source="watch:/project",
        payload={"path": "/project/src/main.py", "action": "modified"},
    )
    goals = router.match(event)
    assert len(goals) == 1
    assert "main.py" in goals[0]


def test_router_respects_cooldown():
    rule = ReactiveRule(
        name="test",
        event_type=EventType.FILESYSTEM,
        source_pattern="*.py",
        goal_template="test",
        cooldown_seconds=60,
    )
    router = EventRouter(rules=[rule])
    event = ObservationEvent(
        event_type=EventType.FILESYSTEM,
        source="watch:/project",
        payload={"path": "main.py"},
    )
    goals1 = router.match(event)
    goals2 = router.match(event)  # within cooldown
    assert len(goals1) == 1
    assert len(goals2) == 0


def test_router_no_match_wrong_event_type():
    rule = ReactiveRule(
        name="test",
        event_type=EventType.SCHEDULED,
        source_pattern="*",
        goal_template="test",
        cooldown_seconds=0,
    )
    router = EventRouter(rules=[rule])
    event = ObservationEvent(
        event_type=EventType.FILESYSTEM,
        source="watch:/project",
        payload={"path": "main.py"},
    )
    assert router.match(event) == []
