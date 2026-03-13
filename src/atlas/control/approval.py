"""Approval Workflow — human-in-the-loop approval for actions requiring permission."""

from __future__ import annotations

import sys

from atlas.contracts.types import ApprovalRequest, ApprovalResult


class ApprovalWorkflow:
    """Handles approval requests. Phase 1: terminal prompts or auto modes for testing."""

    def __init__(
        self,
        auto_approve: bool = False,
        auto_deny: bool = False,
        interactive: bool = True,
    ):
        self._auto_approve = auto_approve
        self._auto_deny = auto_deny
        self._interactive = interactive

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        if self._auto_approve:
            return ApprovalResult.APPROVED
        if self._auto_deny:
            return ApprovalResult.DENIED

        if not self._interactive:
            return ApprovalResult.DENIED

        return self._prompt_terminal(request)

    def _prompt_terminal(self, request: ApprovalRequest) -> ApprovalResult:
        action = request.action
        print(f"\n[approval] {action.description if action else 'Unknown action'}")
        if request.reasoning:
            print(f"  Reason: {request.reasoning}")
        if action:
            print(f"  Risk: {action.risk_level.value}")
            if action.params:
                for k, v in action.params.items():
                    print(f"  {k}: {v}")

        try:
            response = input("  Approve? (y/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return ApprovalResult.DENIED

        if response in ("y", "yes"):
            return ApprovalResult.APPROVED
        return ApprovalResult.DENIED
