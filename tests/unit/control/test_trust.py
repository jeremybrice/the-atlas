import pytest
from atlas.control.trust import TrustTracker
from atlas.contracts.types import AutonomyLevel


@pytest.fixture
async def tracker(db):
    t = TrustTracker(db=db, escalation_threshold=3, demotion_failure_count=2, demotion_window_size=5)
    return t


async def test_record_success_increments(tracker):
    await tracker.record_outcome("file.read", success=True)
    record = await tracker.get_record("file.read")
    assert record.successes == 1
    assert record.consecutive_successes == 1
    assert record.total_invocations == 1


async def test_record_failure_resets_consecutive(tracker):
    await tracker.record_outcome("file.read", success=True)
    await tracker.record_outcome("file.read", success=True)
    await tracker.record_outcome("file.read", success=False)
    record = await tracker.get_record("file.read")
    assert record.successes == 2
    assert record.failures == 1
    assert record.consecutive_successes == 0


async def test_escalation_suggested_after_threshold(tracker):
    # Threshold is 3 for this fixture
    for _ in range(3):
        result = await tracker.record_outcome("file.read", success=True)
    assert result.should_escalate is True


async def test_no_escalation_before_threshold(tracker):
    for _ in range(2):
        result = await tracker.record_outcome("file.read", success=True)
    assert result.should_escalate is False


async def test_demotion_triggered_on_failure_spike(tracker):
    # Window=5, threshold=2 failures
    # First set an override so demotion has something to demote
    await tracker.set_autonomy_override("file.read", AutonomyLevel.ACT_WITHIN_BOUNDS)
    await tracker.record_outcome("file.read", success=True)
    await tracker.record_outcome("file.read", success=False)
    result = await tracker.record_outcome("file.read", success=False)
    assert result.should_demote is True


async def test_get_autonomy_override_none_by_default(tracker):
    override = await tracker.get_autonomy_override("file.read")
    assert override is None


async def test_set_and_get_autonomy_override(tracker):
    await tracker.set_autonomy_override("file.read", AutonomyLevel.ACT_WITHIN_BOUNDS)
    override = await tracker.get_autonomy_override("file.read")
    assert override == AutonomyLevel.ACT_WITHIN_BOUNDS


async def test_get_record_creates_default_if_missing(tracker):
    record = await tracker.get_record("nonexistent.skill")
    assert record.skill_id == "nonexistent.skill"
    assert record.successes == 0


async def test_count_recent_failures_ignores_old_failures(db):
    """A skill with old failures and recent successes should not trigger demotion."""
    tracker = TrustTracker(db=db, escalation_threshold=100, demotion_failure_count=3, demotion_window_size=5)

    # Simulate a skill that had 3 failures long ago, then many successes
    await tracker.set_autonomy_override("file.read", AutonomyLevel.ACT_WITHIN_BOUNDS)
    # Record 3 failures
    for _ in range(3):
        await tracker.record_outcome("file.read", success=False)
    # Record 20 successes (well past the window of 5)
    for _ in range(20):
        await tracker.record_outcome("file.read", success=True)
    # One new failure should NOT trigger demotion (only 1 recent failure, threshold is 3)
    result = await tracker.record_outcome("file.read", success=False)
    assert result.should_demote is False
