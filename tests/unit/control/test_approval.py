

from atlas.contracts.types import (
    ApprovalRequest,
    ApprovalResult,
    ProposedAction,
    RiskLevel,
)
from atlas.control.approval import ApprovalWorkflow


async def test_auto_approve_mode():
    workflow = ApprovalWorkflow(auto_approve=True)
    request = ApprovalRequest(
        action=ProposedAction(
            action_type="filesystem_write",
            domain="skills",
            description="write file",
            risk_level=RiskLevel.MEDIUM,
        ),
        reasoning="needed for task",
    )
    result = await workflow.request_approval(request)
    assert result == ApprovalResult.APPROVED


async def test_auto_deny_mode():
    workflow = ApprovalWorkflow(auto_deny=True)
    request = ApprovalRequest(
        action=ProposedAction(
            action_type="filesystem_write",
            domain="skills",
            description="write file",
        ),
    )
    result = await workflow.request_approval(request)
    assert result == ApprovalResult.DENIED


async def test_non_interactive_denies():
    workflow = ApprovalWorkflow(interactive=False)
    request = ApprovalRequest(
        action=ProposedAction(
            action_type="filesystem_write",
            domain="skills",
            description="write file",
        ),
    )
    result = await workflow.request_approval(request)
    assert result == ApprovalResult.DENIED


async def test_standing_rule_auto_approves(tmp_path):
    from atlas.memory.store import DatabaseStore
    from atlas.control.approval_rules import ApprovalRuleStore
    from atlas.contracts.types import ApprovalRule

    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()
    try:
        rule_store = ApprovalRuleStore(db)
        await rule_store.add_rule(ApprovalRule(match_skill="file.*", decision="allow"))

        workflow = ApprovalWorkflow(rule_store=rule_store)
        request = ApprovalRequest(
            action=ProposedAction(
                action_type="skill_invoke:file.read",
                domain="core",
                description="read file",
                risk_level=RiskLevel.LOW,
                skill_id="file.read",
            ),
        )
        result = await workflow.request_approval(request)
        assert result == ApprovalResult.APPROVED
    finally:
        await db.close()


async def test_standing_deny_rule_blocks(tmp_path):
    from atlas.memory.store import DatabaseStore
    from atlas.control.approval_rules import ApprovalRuleStore
    from atlas.contracts.types import ApprovalRule

    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()
    try:
        rule_store = ApprovalRuleStore(db)
        await rule_store.add_rule(ApprovalRule(match_skill="shell.*", decision="deny"))

        workflow = ApprovalWorkflow(rule_store=rule_store)
        request = ApprovalRequest(
            action=ProposedAction(
                action_type="skill_invoke:shell.execute",
                domain="core",
                description="run command",
                risk_level=RiskLevel.MEDIUM,
                skill_id="shell.execute",
            ),
        )
        result = await workflow.request_approval(request)
        assert result == ApprovalResult.DENIED
    finally:
        await db.close()
