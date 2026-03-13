from atlas.contracts.types import (
    ExecutionContext,
    PolicyDecision,
    AutonomyLevel,
    TaskStatus,
)


def test_execution_context_creates_with_correlation_id():
    ctx = ExecutionContext(correlation_id="abc-123")
    assert ctx.correlation_id == "abc-123"
    assert ctx.mission_id is None
    assert ctx.task_id is None


def test_execution_context_creates_with_all_fields():
    ctx = ExecutionContext(
        correlation_id="abc-123",
        mission_id="mission-1",
        task_id="task-1",
    )
    assert ctx.mission_id == "mission-1"


def test_policy_decision_enum_values():
    assert PolicyDecision.ALLOW.value == "allow"
    assert PolicyDecision.DENY.value == "deny"
    assert PolicyDecision.REQUIRE_APPROVAL.value == "require_approval"


def test_autonomy_level_ordering():
    assert AutonomyLevel.OBSERVE.value < AutonomyLevel.SUGGEST.value
    assert AutonomyLevel.SUGGEST.value < AutonomyLevel.ACT_WITHIN_BOUNDS.value


def test_task_status_terminal_states():
    terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
    non_terminal = {TaskStatus.PENDING, TaskStatus.READY, TaskStatus.EXECUTING}
    for s in terminal:
        assert s.is_terminal()
    for s in non_terminal:
        assert not s.is_terminal()
