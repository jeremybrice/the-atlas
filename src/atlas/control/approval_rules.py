"""Approval Rule Store — persistent standing and batch rules for auto-approval/denial."""

import fnmatch
import logging
from datetime import datetime, timezone

from atlas.contracts.types import ApprovalRule, ProposedAction
from atlas.memory.store import DatabaseStore

logger = logging.getLogger(__name__)

# Risk levels ordered by severity for comparison
_RISK_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


class ApprovalRuleStore:
    """CRUD and matching for persistent approval rules."""

    def __init__(self, db: DatabaseStore) -> None:
        self._db = db

    async def add_rule(self, rule: ApprovalRule) -> str:
        """Insert a rule and return its rule_id."""
        await self._db.db.execute(
            """INSERT INTO approval_rules
               (rule_id, rule_type, match_skill, match_risk, match_path,
                decision, created_at, expires_at, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rule.rule_id,
                rule.rule_type,
                rule.match_skill,
                rule.match_risk,
                rule.match_path,
                rule.decision,
                rule.created_at,
                rule.expires_at,
                rule.description,
            ),
        )
        await self._db.db.commit()
        logger.info(
            "Added approval rule: %s (%s %s -> %s)",
            rule.rule_id,
            rule.match_skill,
            rule.match_risk,
            rule.decision,
        )
        return rule.rule_id

    async def remove_rule(self, rule_id: str) -> bool:
        """Delete a rule. Returns True if it existed."""
        cursor = await self._db.db.execute(
            "DELETE FROM approval_rules WHERE rule_id = ?", (rule_id,)
        )
        await self._db.db.commit()
        return cursor.rowcount > 0

    async def list_rules(self) -> list[ApprovalRule]:
        """Return all non-expired rules."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.db.execute(
            "SELECT rule_id, rule_type, match_skill, match_risk, match_path, "
            "decision, created_at, expires_at, description "
            "FROM approval_rules "
            "WHERE expires_at IS NULL OR expires_at > ?",
            (now,),
        )
        rows = await cursor.fetchall()
        return [
            ApprovalRule(
                rule_id=r[0],
                rule_type=r[1],
                match_skill=r[2],
                match_risk=r[3],
                match_path=r[4],
                decision=r[5],
                created_at=r[6],
                expires_at=r[7],
                description=r[8] or "",
            )
            for r in rows
        ]

    async def find_matching(self, action: ProposedAction) -> ApprovalRule | None:
        """Find the first rule that matches the action. Returns None if no match."""
        rules = await self.list_rules()
        for rule in rules:
            if self._matches(rule, action):
                return rule
        return None

    def _matches(self, rule: ApprovalRule, action: ProposedAction) -> bool:
        """Check if a rule matches an action."""
        skill_id = action.skill_id or ""

        # Match skill pattern (fnmatch glob)
        if rule.match_skill != "*" and not fnmatch.fnmatch(skill_id, rule.match_skill):
            return False

        # Match risk level (rule specifies max risk it covers)
        if rule.match_risk != "*":
            rule_max = _RISK_ORDER.get(rule.match_risk, -1)
            action_risk = _RISK_ORDER.get(action.risk_level.value, 99)
            if action_risk > rule_max:
                return False

        # Match path prefix if specified
        if rule.match_path:
            action_path = action.params.get("path", "")
            if not action_path.startswith(rule.match_path):
                return False

        return True
