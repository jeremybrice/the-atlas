from atlas.contracts.types import (
    AutonomyLevel,
    PolicyDecision,
    ProposedAction,
    RiskLevel,
)
from atlas.control.policy import PolicyEngine


def test_observe_mode_denies_all_actions():
    engine = PolicyEngine(autonomy_level=AutonomyLevel.OBSERVE)
    action = ProposedAction(
        action_type="filesystem_read",
        domain="skills",
        description="read a file",
    )
    assert engine.evaluate(action) == PolicyDecision.DENY


def test_suggest_mode_requires_approval_for_all():
    engine = PolicyEngine(autonomy_level=AutonomyLevel.SUGGEST)
    action = ProposedAction(
        action_type="filesystem_read",
        domain="skills",
        description="read a file",
    )
    assert engine.evaluate(action) == PolicyDecision.REQUIRE_APPROVAL


def test_act_within_bounds_allows_low_risk():
    engine = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    action = ProposedAction(
        action_type="filesystem_read",
        domain="skills",
        description="read a file",
        risk_level=RiskLevel.LOW,
    )
    assert engine.evaluate(action) == PolicyDecision.ALLOW


def test_act_within_bounds_requires_approval_for_medium_risk():
    engine = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    action = ProposedAction(
        action_type="filesystem_write",
        domain="skills",
        description="write a file",
        risk_level=RiskLevel.MEDIUM,
    )
    assert engine.evaluate(action) == PolicyDecision.REQUIRE_APPROVAL


def test_act_within_bounds_requires_approval_for_high_risk():
    engine = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    action = ProposedAction(
        action_type="shell_execute",
        domain="skills",
        description="run a risky command",
        risk_level=RiskLevel.HIGH,
    )
    assert engine.evaluate(action) == PolicyDecision.REQUIRE_APPROVAL


def test_act_within_bounds_denies_critical_risk():
    engine = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    action = ProposedAction(
        action_type="shell_execute",
        domain="skills",
        description="run rm -rf /",
        risk_level=RiskLevel.CRITICAL,
    )
    assert engine.evaluate(action) == PolicyDecision.DENY


def test_blocked_path_is_denied():
    engine = PolicyEngine(
        autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS,
        blocked_paths=["~/.ssh", "~/.gnupg"],
    )
    action = ProposedAction(
        action_type="filesystem_read",
        domain="skills",
        description="read ssh key",
        params={"path": "~/.ssh/id_rsa"},
        risk_level=RiskLevel.LOW,
    )
    assert engine.evaluate(action) == PolicyDecision.DENY


def test_get_autonomy_level():
    engine = PolicyEngine(autonomy_level=AutonomyLevel.SUGGEST)
    assert engine.get_autonomy_level("core") == AutonomyLevel.SUGGEST


def test_per_skill_override_allows_low_risk_when_escalated():
    engine = PolicyEngine(
        autonomy_level=AutonomyLevel.SUGGEST,  # global = suggest (require approval)
        skill_overrides={
            "file.read": AutonomyLevel.ACT_WITHIN_BOUNDS
        },  # per-skill escalated
    )
    action = ProposedAction(
        action_type="filesystem_read",
        domain="skills",
        description="read a file",
        risk_level=RiskLevel.LOW,
        skill_id="file.read",
    )
    assert engine.evaluate(action) == PolicyDecision.ALLOW


def test_per_skill_override_not_applied_to_other_skills():
    engine = PolicyEngine(
        autonomy_level=AutonomyLevel.SUGGEST,
        skill_overrides={"file.read": AutonomyLevel.ACT_WITHIN_BOUNDS},
    )
    action = ProposedAction(
        action_type="shell_execute",
        domain="skills",
        description="run command",
        risk_level=RiskLevel.LOW,
        skill_id="shell.execute",
    )
    # shell.execute has no override, falls back to global SUGGEST
    assert engine.evaluate(action) == PolicyDecision.REQUIRE_APPROVAL


def test_get_autonomy_level_returns_override_when_set():
    engine = PolicyEngine(
        autonomy_level=AutonomyLevel.SUGGEST,
        skill_overrides={"file.read": AutonomyLevel.ACT_WITHIN_BOUNDS},
    )
    assert (
        engine.get_autonomy_level("skills", skill="file.read")
        == AutonomyLevel.ACT_WITHIN_BOUNDS
    )
    assert (
        engine.get_autonomy_level("skills", skill="shell.execute")
        == AutonomyLevel.SUGGEST
    )


def test_evaluate_returns_deny_for_unknown_autonomy_level():
    """PolicyEngine should return DENY (fail-safe) for unrecognized autonomy levels."""
    engine = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    action = ProposedAction(
        action_type="test",
        domain="test",
        description="test action",
        risk_level=RiskLevel.LOW,
        skill_id="bad.skill",
    )
    # Inject a bad override to trigger the default case
    engine._skill_overrides["bad.skill"] = 999
    result = engine.evaluate(action)
    assert result == PolicyDecision.DENY
