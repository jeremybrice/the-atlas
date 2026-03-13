"""Filesystem watcher -- monitors file changes and emits ObservationEvents."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from atlas.contracts.types import ObservationEvent, EventType

logger = logging.getLogger(__name__)


class FilesystemWatcher:
    def __init__(
        self,
        watch_path: str,
        patterns: list[str],
        callback: Callable[[ObservationEvent], Coroutine[Any, Any, None]],
        debounce_seconds: float = 5.0,
    ):
        self._watch_path = watch_path
        self._patterns = patterns
        self._callback = callback
        self._debounce = debounce_seconds
        self._observer: Observer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: dict[str, float] = {}  # path -> last_event_time
        self._debounce_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self._loop = asyncio.get_event_loop()
        self._running = True
        handler = _WatchdogHandler(self._on_raw_event, self._patterns, self._watch_path)
        self._observer = Observer()
        self._observer.schedule(handler, self._watch_path, recursive=True)
        self._observer.start()
        self._debounce_task = asyncio.create_task(self._debounce_loop())

    async def stop(self) -> None:
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join()
        if self._debounce_task:
            self._debounce_task.cancel()
            try:
                await self._debounce_task
            except asyncio.CancelledError:
                pass

    def _on_raw_event(self, path: str, action: str) -> None:
        self._pending[path] = time.monotonic()

    async def _debounce_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._debounce / 2)
            now = time.monotonic()
            ready = [p for p, t in self._pending.items() if now - t >= self._debounce]
            for path in ready:
                del self._pending[path]
                event = ObservationEvent(
                    event_type=EventType.FILESYSTEM,
                    source=f"watch:{self._watch_path}",
                    payload={"path": path, "action": "modified"},
                )
                try:
                    await self._callback(event)
                except Exception as e:
                    logger.error("Watcher callback error: %s", e)


class _WatchdogHandler(FileSystemEventHandler):
    def __init__(self, callback, patterns, watch_path):
        self._callback = callback
        self._patterns = patterns
        self._watch_path = watch_path

    def on_any_event(self, event: FileSystemEvent):
        if event.is_directory:
            return
        path = event.src_path
        rel_path = os.path.relpath(path, self._watch_path)
        if any(
            fnmatch.fnmatch(rel_path, p) or fnmatch.fnmatch(Path(path).name, p)
            for p in self._patterns
        ):
            self._callback(path, event.event_type)
