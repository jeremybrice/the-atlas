# tests/unit/core/test_replan.py
from atlas.core.loop import build_replan_prompt


def test_replan_prompt_includes_error():
    prompt = build_replan_prompt(
        original_goal="add CI workflow",
        failed_task_desc="Read package.json",
        error="File not found: package.json",
        remaining_tasks=["Write CI config", "Commit changes"],
        skills="file.read, file.write, shell.execute",
        context="python project with pyproject.toml",
    )
    assert "package.json" in prompt
    assert "File not found" in prompt
    assert "add CI workflow" in prompt
    assert "pyproject.toml" in prompt


def test_replan_prompt_includes_remaining():
    prompt = build_replan_prompt(
        original_goal="test",
        failed_task_desc="step 2",
        error="oops",
        remaining_tasks=["step 3", "step 4"],
        skills="file.read",
        context="",
    )
    assert "step 3" in prompt
    assert "step 4" in prompt
