import asyncio

import pytest

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
