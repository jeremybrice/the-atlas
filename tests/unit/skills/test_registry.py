# tests/unit/skills/test_registry.py
import pytest

from atlas.contracts.errors import SkillNotFoundError
from atlas.skills.registry import SkillRegistry


@pytest.fixture
def registry() -> SkillRegistry:
    reg = SkillRegistry()

    async def read_handler(params: dict) -> dict:
        return {"content": f"contents of {params['path']}"}

    async def write_handler(params: dict) -> dict:
        return {"written": True}

    reg.register(
        "file.read",
        "Read File",
        "Read contents of a file",
        handler=read_handler,
        risk_level="low",
    )
    reg.register(
        "file.write",
        "Write File",
        "Write content to a file",
        handler=write_handler,
        risk_level="medium",
    )
    return reg


def test_list_all(registry: SkillRegistry):
    skills = registry.list_all()
    assert len(skills) == 2
    ids = [s.skill_id for s in skills]
    assert "file.read" in ids
    assert "file.write" in ids


def test_get_existing(registry: SkillRegistry):
    skill = registry.get("file.read")
    assert skill.name == "Read File"


def test_get_missing_raises():
    reg = SkillRegistry()
    with pytest.raises(SkillNotFoundError):
        reg.get("nonexistent")


def test_search_keyword(registry: SkillRegistry):
    results = registry.search("read")
    assert len(results) >= 1
    assert results[0].skill_id == "file.read"


def test_search_no_match(registry: SkillRegistry):
    results = registry.search("deploy kubernetes")
    assert len(results) == 0
