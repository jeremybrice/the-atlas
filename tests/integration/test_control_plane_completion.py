"""Integration test: control plane completion — emergency, rules, trust recommendations."""

import pytest
from atlas.contracts.types import (
    ApprovalRule,
    ApprovalRequest,
    ApprovalResult,
    AutonomyLevel,
    ProposedAction,
    RiskLevel,
)
from atlas.control.approval import ApprovalWorkflow
from atlas.control.approval_rules import ApprovalRuleStore
from atlas.control.emergency import EmergencyController
from atlas.control.trust import TrustTracker
from atlas.memory.store import DatabaseStore


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


async def test_standing_rule_integrates_with_approval_workflow(db):
    """Standing rule auto-approves without terminal prompt."""
    rule_store = ApprovalRuleStore(db)
    await rule_store.add_rule(
        ApprovalRule(
            match_skill="file.*",
            match_risk="low",
            decision="allow",
        )
    )

    workflow = ApprovalWorkflow(interactive=False, rule_store=rule_store)
    request = ApprovalRequest(
        action=ProposedAction(
            action_type="skill_invoke:file.read",
            domain="core",
            description="read a file",
            risk_level=RiskLevel.LOW,
            skill_id="file.read",
        ),
    )
    result = await workflow.request_approval(request)
    assert result == ApprovalResult.APPROVED


async def test_standing_rule_deny_blocks_even_in_non_interactive(db):
    """A deny rule takes precedence even without interactive mode."""
    rule_store = ApprovalRuleStore(db)
    await rule_store.add_rule(
        ApprovalRule(
            match_skill="shell.*",
            decision="deny",
        )
    )

    workflow = ApprovalWorkflow(interactive=False, rule_store=rule_store)
    request = ApprovalRequest(
        action=ProposedAction(
            action_type="skill_invoke:shell.execute",
            domain="core",
            description="run dangerous command",
            risk_level=RiskLevel.HIGH,
            skill_id="shell.execute",
        ),
    )
    result = await workflow.request_approval(request)
    assert result == ApprovalResult.DENIED


async def test_trust_recommendation_full_lifecycle(db):
    """Create, list, and resolve a trust recommendation."""
    tracker = TrustTracker(
        db=db,
        escalation_threshold=3,
        demotion_failure_count=2,
        demotion_window_size=5,
    )

    # Build up trust
    for _ in range(5):
        await tracker.record_outcome("file.read", success=True)

    # Create recommendation
    rec = await tracker.create_recommendation("file.read", "escalate", mission_id="m1")
    assert rec.status == "pending"

    # Verify it's listed
    pending = await tracker.list_recommendations(status="pending")
    assert len(pending) == 1

    # Accept it
    await tracker.resolve_recommendation(rec.recommendation_id, accepted=True)

    # Verify override was applied
    override = await tracker.get_autonomy_override("file.read")
    assert override == AutonomyLevel.SUGGEST

    # Verify no more pending
    pending = await tracker.list_recommendations(status="pending")
    assert len(pending) == 0


async def test_emergency_controller_state_management():
    """Emergency controller pause/resume/kill flow."""
    ec = EmergencyController()

    assert not ec.is_paused
    ec.pause()
    assert ec.is_paused
    ec.resume()
    assert not ec.is_paused

    ec.set_active_task("t1")
    assert ec.active_task_id == "t1"
    assert ec.kill_task("t1") is True
    assert ec.is_task_cancelled("t1")
    ec.clear_active_task()
    assert ec.active_task_id is None
