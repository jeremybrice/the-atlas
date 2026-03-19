"""Skill data models — definitions, descriptors, and invocation types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from atlas.contracts.types import RiskLevel, SkillDescriptor

# Type alias for async skill handlers
SkillHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


@dataclass
class SkillDefinition:
    """Full skill definition stored in the registry."""

    skill_id: str
    name: str
    description: str
    handler: SkillHandler
    risk_level: RiskLevel = RiskLevel.LOW
    tags: list[str] = field(default_factory=list)

    def to_descriptor(self) -> SkillDescriptor:
        return SkillDescriptor(
            skill_id=self.skill_id,
            name=self.name,
            description=self.description,
            risk_level=self.risk_level,
            tags=self.tags,
        )
