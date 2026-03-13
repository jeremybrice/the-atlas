"""Skill Forge — generates new skills from capability gap descriptions."""
import logging
from dataclasses import dataclass
from pathlib import Path

from atlas.skills.loader import REQUIRED_ATTRS
from atlas.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

FORGE_SYSTEM_PROMPT = (
    "You are a Python skill generator for the ATLAS agent system. "
    "Generate ONLY a valid Python module with these required module-level attributes: "
    "SKILL_ID (str), SKILL_NAME (str), SKILL_DESCRIPTION (str), SKILL_RISK (str: low/medium/high), "
    "and an async handler function: async def handler(params: dict) -> dict. "
    "Output ONLY the Python code, no markdown fences, no explanations."
)

FORGE_PROMPT_TEMPLATE = (
    "Create a Python skill module for this capability gap: {gap}. "
    "Context: {context}. "
    "The handler receives a params dict and must return a result dict. "
    "Use only Python standard library. Set SKILL_RISK to 'high' for safety. "
    "The SKILL_ID must start with 'custom.' prefix."
)


@dataclass
class ForgeResult:
    success: bool
    skill_id: str = ""
    file_path: str = ""
    error: str = ""


class SkillForge:
    def __init__(
        self,
        registry: SkillRegistry,
        claude_bridge,
        skills_dir: str,
        workspace: str,
        max_retries: int = 1,
    ):
        self._registry = registry
        self._claude = claude_bridge
        self._skills_dir = Path(skills_dir)
        self._workspace = workspace
        self._max_retries = max_retries

    async def create_skill(self, gap_description: str, context: str) -> ForgeResult:
        self._skills_dir.mkdir(parents=True, exist_ok=True)

        last_error = ""
        for attempt in range(1 + self._max_retries):
            prompt = FORGE_PROMPT_TEMPLATE.format(gap=gap_description, context=context)
            if attempt > 0:
                prompt += f" Previous attempt failed: {last_error}. Fix the issues."

            response = await self._claude.oneshot(prompt, system_prompt=FORGE_SYSTEM_PROMPT)
            code = self._extract_code(response.content)

            result = self._validate_and_register(code)
            if result.success:
                return result
            last_error = result.error

        return ForgeResult(success=False, error=f"Failed after {1 + self._max_retries} attempts: {last_error}")

    def _extract_code(self, content: str) -> str:
        # Strip markdown fences if present
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            lines = lines[1:]  # remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)
        return content

    def _validate_and_register(self, code: str) -> ForgeResult:
        # Compile check
        try:
            compile(code, "<forge>", "exec")
        except SyntaxError as e:
            return ForgeResult(success=False, error=f"Syntax error: {e}")

        # Execute in isolated namespace
        namespace: dict = {}
        try:
            exec(code, namespace)  # noqa: S102
        except Exception as e:
            return ForgeResult(success=False, error=f"Execution error: {e}")

        # Check required attributes
        for attr in REQUIRED_ATTRS:
            if attr not in namespace:
                return ForgeResult(success=False, error=f"Missing required attribute: {attr}")

        skill_id = namespace["SKILL_ID"]
        if not skill_id.startswith("custom."):
            return ForgeResult(success=False, error=f"SKILL_ID must start with 'custom.': {skill_id}")

        # Save to file
        safe_name = skill_id.replace(".", "_") + ".py"
        file_path = self._skills_dir / safe_name
        file_path.write_text(code)

        # Register
        self._registry.register(
            skill_id=skill_id,
            name=namespace["SKILL_NAME"],
            description=namespace["SKILL_DESCRIPTION"],
            handler=namespace["handler"],
            risk_level="high",  # All forged skills start at high risk per design doc
        )

        logger.info("Forged skill %s -> %s", skill_id, file_path)
        return ForgeResult(success=True, skill_id=skill_id, file_path=str(file_path))
