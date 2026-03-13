"""Task models and queue for the Agent Core execution pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from atlas.contracts.types import TaskStatus, new_id


@dataclass
class Task:
    """A single executable unit of work."""
    description: str
    task_id: str = field(default_factory=new_id)
    mission_id: str | None = None
    skill_id: str | None = None
    input_params: dict[str, Any] = field(default_factory=dict)
    expected_outcome: str = ""
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 3


class TaskQueue:
    """Simple FIFO task queue. Phase 1: no priority, no dependencies."""

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._order: list[str] = []

    def enqueue(self, task: Task) -> None:
        self._tasks[task.task_id] = task
        self._order.append(task.task_id)

    def get_next(self) -> Task | None:
        for task_id in self._order:
            task = self._tasks[task_id]
            if task.status == TaskStatus.PENDING:
                task.status = TaskStatus.EXECUTING
                return task
        return None

    def complete(self, task_id: str, result: Any = None) -> None:
        task = self._tasks[task_id]
        task.status = TaskStatus.COMPLETED
        task.result = result

    def fail(self, task_id: str, error: str = "") -> None:
        task = self._tasks[task_id]
        task.status = TaskStatus.FAILED
        task.error = error

    def size(self) -> int:
        return len(self._tasks)

    def all_tasks(self) -> list[Task]:
        return [self._tasks[tid] for tid in self._order]

    def pending_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING)
