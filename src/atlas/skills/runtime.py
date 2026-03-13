"""Invocation Runtime — executes skills with validation and result packaging."""

from __future__ import annotations

import time

from atlas.contracts.types import ExecutionContext, SkillResult, new_id
from atlas.skills.registry import SkillRegistry


class InvocationRuntime:
    """Executes registered skills and packages results."""

    def __init__(self, registry: SkillRegistry):
        self._registry = registry

    async def invoke(
        self,
        skill_id: str,
        params: dict,
        ctx: ExecutionContext | None = None,
    ) -> SkillResult:
        definition = self._registry.get_definition(skill_id)
        invocation_id = new_id()
        start = time.monotonic()

        try:
            output = await definition.handler(params)
            elapsed = int((time.monotonic() - start) * 1000)
            return SkillResult(
                invocation_id=invocation_id,
                skill_id=skill_id,
                status="success",
                output=output,
                execution_time_ms=elapsed,
            )
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            return SkillResult(
                invocation_id=invocation_id,
                skill_id=skill_id,
                status="failure",
                error=str(e),
                execution_time_ms=elapsed,
            )
