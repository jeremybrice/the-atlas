"""Observation Engine -- coordinates watchers, schedulers, and the event router."""
import logging
from typing import Any, Callable, Coroutine

from atlas.contracts.types import ObservationEvent
from atlas.observation.router import EventRouter
from atlas.observation.scheduler import ScheduledTrigger
from atlas.observation.watcher import FilesystemWatcher

logger = logging.getLogger(__name__)


class ObservationEngine:
    def __init__(
        self,
        router: EventRouter,
        goal_handler: Callable[[str], Coroutine[Any, Any, dict]],
    ):
        self._router = router
        self._goal_handler = goal_handler
        self._watchers: list[FilesystemWatcher] = []
        self._schedulers: list[ScheduledTrigger] = []

    def add_filesystem_watch(
        self, path: str, patterns: list[str], debounce_seconds: float = 5.0
    ) -> None:
        watcher = FilesystemWatcher(
            watch_path=path,
            patterns=patterns,
            callback=self.on_event,
            debounce_seconds=debounce_seconds,
        )
        self._watchers.append(watcher)

    def add_schedule(
        self, name: str, interval_seconds: float, goal_template: str
    ) -> None:
        trigger = ScheduledTrigger(
            name=name,
            interval_seconds=interval_seconds,
            goal_template=goal_template,
            callback=self.on_event,
        )
        self._schedulers.append(trigger)

    async def start(self) -> None:
        for w in self._watchers:
            await w.start()
        for s in self._schedulers:
            await s.start()
        logger.info(
            "Observation engine started: %d watchers, %d schedulers",
            len(self._watchers), len(self._schedulers),
        )

    async def stop(self) -> None:
        for w in self._watchers:
            await w.stop()
        for s in self._schedulers:
            await s.stop()

    async def on_event(self, event: ObservationEvent) -> None:
        goals = self._router.match(event)
        for goal in goals:
            logger.info("Reactive goal triggered: %s (from %s)", goal, event.source)
            try:
                await self._goal_handler(goal)
            except Exception as e:
                logger.error("Goal execution failed: %s", e)
