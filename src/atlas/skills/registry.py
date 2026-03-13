"""Skill Registry — central catalog of available skills."""

from __future__ import annotations

from atlas.contracts.errors import SkillNotFoundError
from atlas.contracts.types import RiskLevel, SkillDescriptor
from atlas.skills.models import SkillDefinition, SkillHandler


class SkillRegistry:
    """In-memory skill registry with keyword search."""

    def __init__(self):
        self._skills: dict[str, SkillDefinition] = {}

    def register(
        self,
        skill_id: str,
        name: str,
        description: str,
        handler: SkillHandler,
        risk_level: str = "low",
        tags: list[str] | None = None,
    ) -> None:
        self._skills[skill_id] = SkillDefinition(
            skill_id=skill_id,
            name=name,
            description=description,
            handler=handler,
            risk_level=RiskLevel(risk_level),
            tags=tags or [],
        )

    def unregister(self, skill_id: str) -> None:
        self._skills.pop(skill_id, None)

    def get(self, skill_id: str) -> SkillDescriptor:
        if skill_id not in self._skills:
            raise SkillNotFoundError(f"Skill not found: {skill_id}")
        return self._skills[skill_id].to_descriptor()

    def get_definition(self, skill_id: str) -> SkillDefinition:
        if skill_id not in self._skills:
            raise SkillNotFoundError(f"Skill not found: {skill_id}")
        return self._skills[skill_id]

    def list_all(self) -> list[SkillDescriptor]:
        return [s.to_descriptor() for s in self._skills.values()]

    def search(self, query: str) -> list[SkillDescriptor]:
        query_lower = query.lower()
        terms = query_lower.split()
        results = []
        for skill in self._skills.values():
            searchable = f"{skill.name} {skill.description} {' '.join(skill.tags)}".lower()
            if all(term in searchable for term in terms):
                results.append(skill.to_descriptor())
        return results
