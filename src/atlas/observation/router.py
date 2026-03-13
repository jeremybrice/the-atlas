"""Event Router -- matches observation events to reactive rules."""

from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass

from atlas.contracts.types import EventType, ObservationEvent


@dataclass
class ReactiveRule:
    name: str
    event_type: EventType
    source_pattern: str
    goal_template: str
    cooldown_seconds: float = 60.0


class EventRouter:
    def __init__(self, rules: list[ReactiveRule] | None = None):
        self._rules = rules or []
        self._last_fired: dict[str, float] = {}

    def add_rule(self, rule: ReactiveRule) -> None:
        self._rules.append(rule)

    def match(self, event: ObservationEvent) -> list[str]:
        goals = []
        now = time.monotonic()
        for rule in self._rules:
            if rule.event_type != event.event_type:
                continue
            path = event.payload.get("path", "")
            if not fnmatch.fnmatch(path, rule.source_pattern) and rule.source_pattern != "*":
                # Also check just the filename
                if not fnmatch.fnmatch(path.rsplit("/", 1)[-1], rule.source_pattern):
                    continue
            # Cooldown check
            last = self._last_fired.get(rule.name, 0)
            if now - last < rule.cooldown_seconds:
                continue
            self._last_fired[rule.name] = now
            # Template substitution
            goal = rule.goal_template.format(**event.payload)
            goals.append(goal)
        return goals
