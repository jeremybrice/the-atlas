import pytest
from atlas.contracts.types import ApprovalRule, ProposedAction, RiskLevel
from atlas.control.approval_rules import ApprovalRuleStore
from atlas.memory.store import DatabaseStore


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def rule_store(db):
    return ApprovalRuleStore(db)


async def test_add_and_list_rule(rule_store):
    rule = ApprovalRule(
        match_skill="file.*", decision="allow", description="allow all file ops"
    )
    rule_id = await rule_store.add_rule(rule)
    assert rule_id == rule.rule_id

    rules = await rule_store.list_rules()
    assert len(rules) == 1
    assert rules[0].match_skill == "file.*"


async def test_remove_rule(rule_store):
    rule = ApprovalRule(match_skill="file.*", decision="allow")
    await rule_store.add_rule(rule)

    removed = await rule_store.remove_rule(rule.rule_id)
    assert removed is True

    rules = await rule_store.list_rules()
    assert len(rules) == 0


async def test_remove_nonexistent_returns_false(rule_store):
    removed = await rule_store.remove_rule("nonexistent-id")
    assert removed is False


async def test_find_matching_skill_glob(rule_store):
    await rule_store.add_rule(ApprovalRule(match_skill="file.*", decision="allow"))

    action = ProposedAction(
        action_type="skill_invoke:file.read",
        domain="core",
        description="read file",
        risk_level=RiskLevel.LOW,
        skill_id="file.read",
    )
    match = await rule_store.find_matching(action)
    assert match is not None
    assert match.decision == "allow"


async def test_find_matching_wildcard_skill(rule_store):
    await rule_store.add_rule(
        ApprovalRule(match_skill="*", match_risk="low", decision="allow")
    )

    action = ProposedAction(
        action_type="skill_invoke:shell.execute",
        domain="core",
        description="run command",
        risk_level=RiskLevel.LOW,
        skill_id="shell.execute",
    )
    match = await rule_store.find_matching(action)
    assert match is not None


async def test_find_matching_respects_risk_level(rule_store):
    await rule_store.add_rule(
        ApprovalRule(match_skill="*", match_risk="low", decision="allow")
    )

    action = ProposedAction(
        action_type="skill_invoke:shell.execute",
        domain="core",
        description="run command",
        risk_level=RiskLevel.HIGH,
        skill_id="shell.execute",
    )
    match = await rule_store.find_matching(action)
    assert match is None  # HIGH risk doesn't match "low" rule


async def test_find_matching_deny_rule(rule_store):
    await rule_store.add_rule(ApprovalRule(match_skill="shell.*", decision="deny"))

    action = ProposedAction(
        action_type="skill_invoke:shell.execute",
        domain="core",
        description="run command",
        risk_level=RiskLevel.LOW,
        skill_id="shell.execute",
    )
    match = await rule_store.find_matching(action)
    assert match is not None
    assert match.decision == "deny"


async def test_expired_rules_are_skipped(rule_store):
    await rule_store.add_rule(
        ApprovalRule(
            match_skill="file.*",
            decision="allow",
            expires_at="2020-01-01T00:00:00+00:00",  # already expired
        )
    )

    action = ProposedAction(
        action_type="skill_invoke:file.read",
        domain="core",
        description="read file",
        risk_level=RiskLevel.LOW,
        skill_id="file.read",
    )
    match = await rule_store.find_matching(action)
    assert match is None


async def test_no_rules_returns_none(rule_store):
    action = ProposedAction(
        action_type="skill_invoke:file.read",
        domain="core",
        description="read file",
        risk_level=RiskLevel.LOW,
        skill_id="file.read",
    )
    match = await rule_store.find_matching(action)
    assert match is None
