"""Policy Engine — evaluates proposed actions against autonomy rules and boundaries."""

from __future__ import annotations

from pathlib import Path

from atlas.contracts.types import (
    AutonomyLevel,
    PolicyDecision,
    ProposedAction,
    RiskLevel,
)


class PolicyEngine:
    """Stateless policy evaluator. Every action passes through evaluate()."""

    def __init__(
        self,
        autonomy_level: AutonomyLevel = AutonomyLevel.ACT_WITHIN_BOUNDS,
        blocked_paths: list[str] | None = None,
    ):
        self._autonomy_level = autonomy_level
        self._blocked_paths = [
            str(Path(p).expanduser()) for p in (blocked_paths or [])
        ]

    def evaluate(self, action: ProposedAction) -> PolicyDecision:
        # Check blocked paths first
        if self._is_blocked_path(action):
            return PolicyDecision.DENY

        match self._autonomy_level:
            case AutonomyLevel.OBSERVE:
                return PolicyDecision.DENY
            case AutonomyLevel.SUGGEST:
                return PolicyDecision.REQUIRE_APPROVAL
            case AutonomyLevel.ACT_WITHIN_BOUNDS:
                return self._evaluate_bounded(action)

    def _evaluate_bounded(self, action: ProposedAction) -> PolicyDecision:
        match action.risk_level:
            case RiskLevel.LOW:
                return PolicyDecision.ALLOW
            case RiskLevel.MEDIUM:
                return PolicyDecision.REQUIRE_APPROVAL
            case RiskLevel.HIGH:
                return PolicyDecision.REQUIRE_APPROVAL
            case RiskLevel.CRITICAL:
                return PolicyDecision.DENY

    def _is_blocked_path(self, action: ProposedAction) -> bool:
        path_str = action.params.get("path", "")
        if not path_str:
            return False
        resolved = str(Path(path_str).expanduser())
        return any(resolved.startswith(bp) for bp in self._blocked_paths)

    def get_autonomy_level(self, domain: str, skill: str | None = None) -> AutonomyLevel:
        return self._autonomy_level
