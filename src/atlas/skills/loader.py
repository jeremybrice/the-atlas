"""Skill Loader — loads custom skills from Python files in a directory."""
import importlib.util
import logging
from pathlib import Path

from atlas.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

REQUIRED_ATTRS = ["SKILL_ID", "SKILL_NAME", "SKILL_DESCRIPTION", "SKILL_RISK", "handler"]


def load_skills_from_directory(directory: str, registry: SkillRegistry) -> int:
    skill_dir = Path(directory)
    if not skill_dir.is_dir():
        return 0

    count = 0
    for path in sorted(skill_dir.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(path.stem, path)
            if not spec or not spec.loader:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Validate required attributes
            if not all(hasattr(module, attr) for attr in REQUIRED_ATTRS):
                logger.debug("Skipping %s: missing required attributes", path.name)
                continue

            registry.register(
                skill_id=module.SKILL_ID,
                name=module.SKILL_NAME,
                description=module.SKILL_DESCRIPTION,
                handler=module.handler,
                risk_level=module.SKILL_RISK,
            )
            count += 1
            logger.info("Loaded skill: %s from %s", module.SKILL_ID, path.name)
        except Exception as e:
            logger.warning("Failed to load skill from %s: %s", path.name, e)

    return count
