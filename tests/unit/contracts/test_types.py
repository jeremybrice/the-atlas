from atlas.contracts.types import (
    ExecutionContext,
    PolicyDecision,
    AutonomyLevel,
    TaskStatus,
    ObservationEvent,
    EventType,
    Procedure,
    DaemonCommand,
    DaemonResponse,
    TrustRecord,
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



def test_observation_event_creation():
    event = ObservationEvent(
        event_type=EventType.FILESYSTEM,
        source="watch:src/**/*.py",
        payload={"path": "src/main.py", "action": "modified"},
    )
    assert event.event_id  # auto-generated
    assert event.priority == 5


def test_procedure_creation():
    proc = Procedure(
        name="run-tests",
        description="Run pytest after source change",
        trigger_pattern="filesystem:src/**/*.py",
        steps=[{"skill": "shell.execute", "params": {"command": "pytest"}}],
    )
    assert proc.procedure_id  # auto-generated
    assert proc.success_rate == 0.0


def test_daemon_command_and_response():
    cmd = DaemonCommand(command="goal", payload={"goal_text": "do thing"})
    assert cmd.command_id  # auto-generated
    resp = DaemonResponse(command_id=cmd.command_id, status="ok", payload={"mission_id": "abc"})
    assert resp.status == "ok"


def test_trust_record_defaults():
    record = TrustRecord(skill_id="file.read")
    assert record.skill_id == "file.read"
    assert record.successes == 0
    assert record.failures == 0
    assert record.consecutive_successes == 0
    assert record.autonomy_override is None


def test_trust_record_with_values():
    record = TrustRecord(
        skill_id="file.read",
        successes=10,
        failures=1,
        consecutive_successes=5,
    )
    assert record.successes == 10
    assert record.failures == 1
    assert record.consecutive_successes == 5
