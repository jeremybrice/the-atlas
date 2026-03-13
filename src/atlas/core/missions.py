"""Mission Planner — decomposes goals into task lists via Claude Code."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from atlas.contracts.types import MissionStatus, new_id
from atlas.core.tasks import Task


@dataclass
class Mission:
    """A user-assigned goal with its task list and state."""
    mission_id: str = field(default_factory=new_id)
    goal_text: str = ""
    status: MissionStatus = MissionStatus.PLANNING
    tasks: list[Task] = field(default_factory=list)


def parse_task_plan(raw: str) -> list[Task]:
    """Parse Claude Code response into a list of Tasks.

    Tries JSON first (structured), falls back to numbered list (unstructured).
    """
    if not raw.strip():
        return []

    # Try JSON block in markdown
    json_match = re.search(r"```json\s*\n(.*?)\n```", raw, re.DOTALL)
    if json_match:
        return _parse_json_tasks(json_match.group(1))

    # Try raw JSON
    try:
        return _parse_json_tasks(raw)
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    # Fallback: numbered list
    return _parse_numbered_list(raw)


def _parse_json_tasks(json_str: str) -> list[Task]:
    data = json.loads(json_str)
    tasks = []
    for item in data.get("tasks", []):
        tasks.append(Task(
            description=item.get("description", ""),
            skill_id=item.get("skill"),
            input_params=item.get("params", {}),
            expected_outcome=item.get("expected_outcome", ""),
        ))
    return tasks


def _parse_numbered_list(text: str) -> list[Task]:
    pattern = r"^\s*\d+[\.\)]\s*(.+)$"
    tasks = []
    for match in re.finditer(pattern, text, re.MULTILINE):
        description = match.group(1).strip()
        if description:
            tasks.append(Task(description=description))
    return tasks


PLANNING_PROMPT_TEMPLATE = """You are ATLAS, an autonomous agent. Decompose the following goal into a sequence of executable tasks.

GOAL: {goal}

AVAILABLE SKILLS:
{skills}

ENVIRONMENT STATE:
{env_state}

Respond with a JSON block:
```json
{{
  "tasks": [
    {{"description": "what this step does", "skill": "skill.id", "params": {{"key": "value"}}}},
    ...
  ]
}}
```

Keep the plan simple and linear. Use only the available skills. Each task should be one skill invocation."""
