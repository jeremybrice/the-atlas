# tests/unit/skills/test_seed.py
from pathlib import Path

import pytest

from atlas.env.filesystem import FilesystemProvider
from atlas.env.process import ProcessProvider
from atlas.skills.registry import SkillRegistry
from atlas.skills.seed import register_seed_skills


@pytest.fixture
def seeded_registry(tmp_workspace: Path) -> SkillRegistry:
    registry = SkillRegistry()
    fs = FilesystemProvider(workspace=str(tmp_workspace))
    proc = ProcessProvider()
    register_seed_skills(registry, fs, proc)
    return registry


def test_seed_skills_registered(seeded_registry: SkillRegistry):
    skills = seeded_registry.list_all()
    ids = [s.skill_id for s in skills]
    assert "file.read" in ids
    assert "file.write" in ids
    assert "file.search" in ids
    assert "shell.execute" in ids


async def test_file_read_skill(seeded_registry: SkillRegistry, tmp_workspace: Path):
    defn = seeded_registry.get_definition("file.read")
    result = await defn.handler({"path": str(tmp_workspace / "src" / "main.py")})
    assert "hello" in result["content"]


async def test_file_write_skill(seeded_registry: SkillRegistry, tmp_workspace: Path):
    path = str(tmp_workspace / "new_file.txt")
    defn = seeded_registry.get_definition("file.write")
    result = await defn.handler({"path": path, "content": "new content"})
    assert result["written"] is True
    assert Path(path).read_text() == "new content"


async def test_file_search_skill(seeded_registry: SkillRegistry, tmp_workspace: Path):
    defn = seeded_registry.get_definition("file.search")
    result = await defn.handler({"root": str(tmp_workspace), "pattern": "**/*.py"})
    assert len(result["matches"]) >= 1


async def test_shell_execute_skill(seeded_registry: SkillRegistry):
    defn = seeded_registry.get_definition("shell.execute")
    result = await defn.handler({"command": "echo test123"})
    assert "test123" in result["stdout"]
    assert result["exit_code"] == 0
