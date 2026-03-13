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
