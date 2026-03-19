"""Integration test: TrustTracker + PolicyEngine + CredentialVault working together."""

import pytest
from atlas.control.policy import PolicyEngine
from atlas.control.trust import TrustTracker
from atlas.contracts.types import (
    AutonomyLevel,
    PolicyDecision,
    ProposedAction,
    RiskLevel,
)
from atlas.integrations.vault import CredentialVault


@pytest.fixture
async def components(db):
    tracker = TrustTracker(
        db=db, escalation_threshold=3, demotion_failure_count=2, demotion_window_size=5
    )
    policy = PolicyEngine(autonomy_level=AutonomyLevel.SUGGEST)
    vault = await CredentialVault.create(db=db, passphrase="integration-test")
    return tracker, policy, vault


async def test_trust_escalation_changes_policy_decision(components):
    tracker, policy, _ = components

    # Initially, SUGGEST mode requires approval for everything
    action = ProposedAction(
        action_type="filesystem_read",
        domain="skills",
        description="read file",
        risk_level=RiskLevel.LOW,
        skill_id="file.read",
    )
    assert policy.evaluate(action) == PolicyDecision.REQUIRE_APPROVAL

    # Record 3 successes (threshold) for file.read
    for _ in range(3):
        outcome = await tracker.record_outcome("file.read", success=True)

    assert outcome.should_escalate is True

    # Simulate user approving escalation
    await tracker.set_autonomy_override("file.read", AutonomyLevel.ACT_WITHIN_BOUNDS)
    policy.set_skill_override("file.read", AutonomyLevel.ACT_WITHIN_BOUNDS)

    # Now file.read should be ALLOW (low risk + ACT_WITHIN_BOUNDS)
    assert policy.evaluate(action) == PolicyDecision.ALLOW

    # Other skills still require approval
    other_action = ProposedAction(
        action_type="shell_execute",
        domain="skills",
        description="run command",
        risk_level=RiskLevel.LOW,
        skill_id="shell.execute",
    )
    assert policy.evaluate(other_action) == PolicyDecision.REQUIRE_APPROVAL


async def test_trust_demotion_reverts_policy(components):
    tracker, policy, _ = components

    # Set up an escalated skill
    await tracker.set_autonomy_override("file.read", AutonomyLevel.ACT_WITHIN_BOUNDS)
    policy.set_skill_override("file.read", AutonomyLevel.ACT_WITHIN_BOUNDS)

    action = ProposedAction(
        action_type="filesystem_read",
        domain="skills",
        description="read file",
        risk_level=RiskLevel.LOW,
        skill_id="file.read",
    )
    assert policy.evaluate(action) == PolicyDecision.ALLOW

    # Record failures until demotion triggers
    await tracker.record_outcome("file.read", success=False)
    outcome = await tracker.record_outcome("file.read", success=False)
    assert outcome.should_demote is True

    # Apply demotion
    policy.remove_skill_override("file.read")
    # Now falls back to global SUGGEST
    assert policy.evaluate(action) == PolicyDecision.REQUIRE_APPROVAL


async def test_vault_stores_and_retrieves_across_sessions(db):
    """Verify vault data persists across CredentialVault instances."""
    vault1 = await CredentialVault.create(db=db, passphrase="same-pass")
    await vault1.store("github", "token", "ghp_secret123")

    vault2 = await CredentialVault.create(db=db, passphrase="same-pass")
    result = await vault2.get("github", "token")
    assert result == "ghp_secret123"


async def test_vault_wrong_passphrase_fails(db):
    from atlas.contracts.errors import CredentialError

    vault1 = await CredentialVault.create(db=db, passphrase="correct-pass")
    await vault1.store("github", "token", "ghp_secret123")

    vault2 = await CredentialVault.create(db=db, passphrase="wrong-pass")
    with pytest.raises(CredentialError):
        await vault2.get("github", "token")
