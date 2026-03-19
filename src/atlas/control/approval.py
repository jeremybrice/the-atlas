"""Approval Workflow — human-in-the-loop approval for actions requiring permission."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from atlas.contracts.types import ApprovalRequest, ApprovalResult

if TYPE_CHECKING:
    from atlas.control.approval_rules import ApprovalRuleStore

logger = logging.getLogger(__name__)


class ApprovalWorkflow:
    """Handles approval requests with optional standing rules."""

    def __init__(
        self,
        auto_approve: bool = False,
        auto_deny: bool = False,
        interactive: bool = True,
        rule_store: ApprovalRuleStore | None = None,
    ):
        self._auto_approve = auto_approve
        self._auto_deny = auto_deny
        self._interactive = interactive
        self._rule_store = rule_store

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        if self._auto_approve:
            return ApprovalResult.APPROVED
        if self._auto_deny:
            return ApprovalResult.DENIED

        # Check standing rules
        if self._rule_store and request.action:
            match = await self._rule_store.find_matching(request.action)
            if match:
                decision = (
                    ApprovalResult.APPROVED
                    if match.decision == "allow"
                    else ApprovalResult.DENIED
                )
                logger.info(
                    "Standing rule %s matched: %s", match.rule_id, match.decision
                )
                return decision

        if not self._interactive:
            return ApprovalResult.DENIED

        return await self._prompt_terminal(request)

    async def request_batch_approval(
        self,
        requests: list[ApprovalRequest],
    ) -> list[ApprovalResult]:
        """Approve or deny a batch of requests together."""
        if self._auto_approve:
            return [ApprovalResult.APPROVED] * len(requests)
        if self._auto_deny:
            return [ApprovalResult.DENIED] * len(requests)

        # Check standing rules first — auto-resolve what we can
        results: list[ApprovalResult | None] = [None] * len(requests)
        pending_indices: list[int] = []

        if self._rule_store:
            for i, req in enumerate(requests):
                if req.action:
                    match = await self._rule_store.find_matching(req.action)
                    if match:
                        results[i] = (
                            ApprovalResult.APPROVED
                            if match.decision == "allow"
                            else ApprovalResult.DENIED
                        )
                        continue
                pending_indices.append(i)
        else:
            pending_indices = list(range(len(requests)))

        if not pending_indices:
            return results  # all resolved by rules

        if not self._interactive:
            for i in pending_indices:
                results[i] = ApprovalResult.DENIED
            return results

        # Present batch prompt for remaining
        print(f"\n[approval] {len(pending_indices)} actions pending:")
        for idx, i in enumerate(pending_indices, 1):
            req = requests[i]
            action = req.action
            desc = action.description if action else "Unknown"
            risk = action.risk_level.value if action else "unknown"
            skill = action.skill_id if action else "unknown"
            print(f"  {idx}. {skill} — {desc} ({risk.upper()} risk)")

        try:
            response = input("Approve all? (y/n/select): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            for i in pending_indices:
                results[i] = ApprovalResult.DENIED
            return results

        if response in ("y", "yes"):
            for i in pending_indices:
                results[i] = ApprovalResult.APPROVED
        elif response == "select":
            for i in pending_indices:
                results[i] = await self._prompt_terminal(requests[i])
        else:
            for i in pending_indices:
                results[i] = ApprovalResult.DENIED

        return results

    async def _prompt_terminal(self, request: ApprovalRequest) -> ApprovalResult:
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
            response = input("  Approve? (y/n/always/never): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return ApprovalResult.DENIED

        if response == "always" and self._rule_store and action:
            from atlas.contracts.types import ApprovalRule

            rule = ApprovalRule(
                match_skill=action.skill_id or "*",
                match_risk=action.risk_level.value,
                decision="allow",
                description=f"Standing allow for {action.skill_id}",
            )
            await self._rule_store.add_rule(rule)
            print(f"  [rule] Created standing ALLOW rule for {action.skill_id}")
            return ApprovalResult.APPROVED
        elif response == "never" and self._rule_store and action:
            from atlas.contracts.types import ApprovalRule

            rule = ApprovalRule(
                match_skill=action.skill_id or "*",
                match_risk=action.risk_level.value,
                decision="deny",
                description=f"Standing deny for {action.skill_id}",
            )
            await self._rule_store.add_rule(rule)
            print(f"  [rule] Created standing DENY rule for {action.skill_id}")
            return ApprovalResult.DENIED
        elif response in ("y", "yes"):
            return ApprovalResult.APPROVED
        return ApprovalResult.DENIED
