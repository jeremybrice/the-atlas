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

    # Try JSON block in markdown (```json ... ```)
    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", raw, re.DOTALL)
    if json_match:
        try:
            tasks = _parse_json_tasks(json_match.group(1))
            if tasks:
                return tasks
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    # Try to find JSON object anywhere in the text
    json_obj_match = re.search(r"\{.*\"tasks\"\s*:", raw, re.DOTALL)
    if json_obj_match:
        # Find the matching closing brace
        start = json_obj_match.start()
        try:
            tasks = _parse_json_tasks(raw[start:])
            if tasks:
                return tasks
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    # Try raw JSON (entire response is JSON)
    try:
        tasks = _parse_json_tasks(raw)
        if tasks:
            return tasks
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


PLANNING_PROMPT_TEMPLATE = """Respond with only JSON. Goal: {goal}. Skills: {skills}. Format: {{"tasks":[{{"description":"...","skill":"skill.id","params":{{}}}}]}}"""
