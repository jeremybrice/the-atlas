# tests/unit/core/test_missions.py
import json


from atlas.core.missions import parse_task_plan


def test_parse_task_plan_json():
    raw = json.dumps(
        {
            "tasks": [
                {
                    "description": "Read the file",
                    "skill": "file.read",
                    "params": {"path": "main.py"},
                },
                {
                    "description": "Modify the code",
                    "skill": "file.write",
                    "params": {"path": "main.py", "content": "new"},
                },
            ]
        }
    )
    tasks = parse_task_plan(raw)
    assert len(tasks) == 2
    assert tasks[0].skill_id == "file.read"
    assert tasks[0].input_params["path"] == "main.py"
    assert tasks[1].skill_id == "file.write"


def test_parse_task_plan_json_in_markdown():
    raw = """Here's the plan:
```json
{"tasks": [{"description": "Run tests", "skill": "shell.execute", "params": {"command": "pytest"}}]}
```
That should work."""
    tasks = parse_task_plan(raw)
    assert len(tasks) == 1
    assert tasks[0].skill_id == "shell.execute"


def test_parse_task_plan_fallback_numbered_list():
    raw = """Here's what I'll do:
1. Read the file src/main.py
2. Add error handling to the main function
3. Write the updated file back"""
    tasks = parse_task_plan(raw)
    assert len(tasks) == 3
    assert "Read the file" in tasks[0].description


def test_parse_task_plan_empty():
    tasks = parse_task_plan("")
    assert tasks == []
