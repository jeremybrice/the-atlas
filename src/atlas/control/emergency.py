"""Emergency Controller — pause, resume, and kill operations for the daemon."""
import asyncio
import logging

logger = logging.getLogger(__name__)


class EmergencyController:
    """Manages daemon pause/resume state and task cancellation."""

    def __init__(self) -> None:
        self._running = asyncio.Event()
        self._running.set()  # starts unpaused
        self._active_task_id: str | None = None
        self._cancelled_tasks: set[str] = set()

    @property
    def is_paused(self) -> bool:
        return not self._running.is_set()

    @property
    def active_task_id(self) -> str | None:
        return self._active_task_id

    def pause(self) -> None:
        """Pause the execution loop. Running tasks finish; new tasks wait."""
        self._running.clear()
        logger.info("Emergency: execution paused")

    def resume(self) -> None:
        """Resume the execution loop."""
        self._running.set()
        self._cancelled_tasks.clear()
        logger.info("Emergency: execution resumed")

    async def wait_if_paused(self) -> None:
        """Block until resumed. Call before each task execution."""
        await self._running.wait()

    def set_active_task(self, task_id: str) -> None:
        self._active_task_id = task_id

    def clear_active_task(self) -> None:
        self._active_task_id = None

    def kill_task(self, task_id: str) -> bool:
        """Mark a task for cancellation. Returns True if the task is active."""
        if self._active_task_id == task_id:
            self._cancelled_tasks.add(task_id)
            logger.info("Emergency: task %s marked for cancellation", task_id)
            return True
        return False

    def is_task_cancelled(self, task_id: str) -> bool:
        return task_id in self._cancelled_tasks
