"""Scheduled trigger -- fires ObservationEvents on a recurring interval."""

import asyncio
import logging
from typing import Any, Callable, Coroutine

from atlas.contracts.types import ObservationEvent, EventType

logger = logging.getLogger(__name__)


class ScheduledTrigger:
    def __init__(
        self,
        name: str,
        interval_seconds: float,
        goal_template: str,
        callback: Callable[[ObservationEvent], Coroutine[Any, Any, None]],
    ):
        self._name = name
        self._interval = interval_seconds
        self._goal_template = goal_template
        self._callback = callback
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._interval)
            if not self._running:
                break
            event = ObservationEvent(
                event_type=EventType.SCHEDULED,
                source=f"schedule:{self._name}",
                payload={"goal": self._goal_template},
            )
            try:
                await self._callback(event)
            except Exception as e:
                logger.error("Scheduled trigger %s error: %s", self._name, e)
