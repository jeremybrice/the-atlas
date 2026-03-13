# tests/unit/skills/test_forge.py
import pytest
from unittest.mock import AsyncMock
from atlas.skills.forge import SkillForge
from atlas.skills.registry import SkillRegistry
from atlas.contracts.types import ClaudeResponse


@pytest.fixture
def forge_env(tmp_path):
    registry = SkillRegistry()
    claude = AsyncMock()
    return {
        "registry": registry,
        "claude": claude,
        "skills_dir": str(tmp_path / "skills"),
        "workspace": str(tmp_path),
    }


async def test_forge_generates_skill(forge_env):
    # Mock Claude returning valid skill code
    skill_code = '''
SKILL_ID = "custom.count_lines"
SKILL_NAME = "Count Lines"
SKILL_DESCRIPTION = "Counts lines in a file"
SKILL_RISK = "high"

async def handler(params):
    path = params["path"]
    with open(path) as f:
        return {"count": len(f.readlines())}
'''
    forge_env["claude"].oneshot = AsyncMock(return_value=ClaudeResponse(
        content=skill_code, parsed_output=None
    ))

    forge = SkillForge(
        registry=forge_env["registry"],
        claude_bridge=forge_env["claude"],
        skills_dir=forge_env["skills_dir"],
        workspace=forge_env["workspace"],
    )
    result = await forge.create_skill(
        gap_description="I need to count lines in a file",
        context="working with text files",
    )
    assert result.success
    assert result.skill_id == "custom.count_lines"
    assert forge_env["registry"].get("custom.count_lines") is not None


async def test_forge_handles_invalid_code(forge_env):
    forge_env["claude"].oneshot = AsyncMock(return_value=ClaudeResponse(
        content="this is not valid python {{{{", parsed_output=None
    ))
    forge = SkillForge(
        registry=forge_env["registry"],
        claude_bridge=forge_env["claude"],
        skills_dir=forge_env["skills_dir"],
        workspace=forge_env["workspace"],
    )
    result = await forge.create_skill(gap_description="do something", context="")
    assert not result.success
    assert result.error
