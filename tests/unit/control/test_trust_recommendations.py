import pytest
from atlas.contracts.types import AutonomyLevel
from atlas.control.trust import TrustTracker
from atlas.memory.store import DatabaseStore


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
def tracker(db):
    return TrustTracker(
        db=db, escalation_threshold=3, demotion_failure_count=2, demotion_window_size=5
    )


async def test_create_escalation_recommendation(tracker):
    # Record enough successes to warrant escalation
    for _ in range(5):
        await tracker.record_outcome("file.read", success=True)

    rec = await tracker.create_recommendation("file.read", "escalate", mission_id="m1")
    assert rec.skill_id == "file.read"
    assert rec.direction == "escalate"
    assert rec.status == "pending"
    assert rec.recommended_level == "SUGGEST"  # from None → SUGGEST
    assert rec.evidence["success_rate"] > 0
    assert rec.mission_id == "m1"


async def test_create_demotion_recommendation(tracker, db):
    # Set an override first
    await tracker.set_autonomy_override(
        "shell.execute", AutonomyLevel.ACT_WITHIN_BOUNDS
    )
    await tracker.record_outcome("shell.execute", success=False)

    rec = await tracker.create_recommendation(
        "shell.execute", "demote", mission_id="m1"
    )
    assert rec.direction == "demote"
    assert rec.recommended_level == "SUGGEST"  # from ACT_WITHIN_BOUNDS → SUGGEST


async def test_list_recommendations_filters_by_status(tracker):
    await tracker.record_outcome("file.read", success=True)
    await tracker.create_recommendation("file.read", "escalate", mission_id="m1")

    pending = await tracker.list_recommendations(status="pending")
    assert len(pending) == 1

    dismissed = await tracker.list_recommendations(status="dismissed")
    assert len(dismissed) == 0


async def test_resolve_recommendation_accepted(tracker):
    await tracker.record_outcome("file.read", success=True)
    rec = await tracker.create_recommendation("file.read", "escalate", mission_id="m1")

    await tracker.resolve_recommendation(rec.recommendation_id, accepted=True)

    # Recommendation should be accepted
    pending = await tracker.list_recommendations(status="pending")
    assert len(pending) == 0

    accepted = await tracker.list_recommendations(status="accepted")
    assert len(accepted) == 1

    # Autonomy override should be applied
    override = await tracker.get_autonomy_override("file.read")
    assert override == AutonomyLevel.SUGGEST


async def test_resolve_recommendation_dismissed(tracker):
    await tracker.record_outcome("file.read", success=True)
    rec = await tracker.create_recommendation("file.read", "escalate", mission_id="m1")

    await tracker.resolve_recommendation(rec.recommendation_id, accepted=False)

    dismissed = await tracker.list_recommendations(status="dismissed")
    assert len(dismissed) == 1

    # No autonomy override should be applied
    override = await tracker.get_autonomy_override("file.read")
    assert override is None
