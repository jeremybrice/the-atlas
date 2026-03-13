# tests/unit/skills/test_loader.py
from atlas.skills.loader import load_skills_from_directory
from atlas.skills.registry import SkillRegistry


def test_load_skill_from_file(tmp_path):
    skill_file = tmp_path / "greet.py"
    skill_file.write_text('''
SKILL_ID = "custom.greet"
SKILL_NAME = "Greet"
SKILL_DESCRIPTION = "Says hello"
SKILL_RISK = "low"

async def handler(params):
    name = params.get("name", "world")
    return {"greeting": f"hello {name}"}
''')
    registry = SkillRegistry()
    count = load_skills_from_directory(str(tmp_path), registry)
    assert count == 1
    desc = registry.get("custom.greet")
    assert desc.name == "Greet"
    assert desc.risk_level.value == "low"


def test_load_skips_invalid_files(tmp_path):
    (tmp_path / "bad.py").write_text("x = 1")  # missing SKILL_ID
    (tmp_path / "notpy.txt").write_text("SKILL_ID = 'x'")  # wrong extension
    registry = SkillRegistry()
    count = load_skills_from_directory(str(tmp_path), registry)
    assert count == 0


async def test_loaded_skill_is_invocable(tmp_path):
    skill_file = tmp_path / "echo.py"
    skill_file.write_text('''
SKILL_ID = "custom.echo"
SKILL_NAME = "Echo"
SKILL_DESCRIPTION = "Echoes input"
SKILL_RISK = "low"

async def handler(params):
    return {"echoed": params.get("text", "")}
''')
    registry = SkillRegistry()
    load_skills_from_directory(str(tmp_path), registry)
    from atlas.skills.runtime import InvocationRuntime
    runtime = InvocationRuntime(registry)
    result = await runtime.invoke("custom.echo", {"text": "hi"})
    assert result.status == "success"
    assert result.output["echoed"] == "hi"
