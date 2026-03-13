import asyncio
from atlas.observation.watcher import FilesystemWatcher
from atlas.contracts.types import ObservationEvent, EventType


async def test_filesystem_watcher_detects_file_creation(tmp_path):
    events: list[ObservationEvent] = []

    async def on_event(event: ObservationEvent):
        events.append(event)

    watcher = FilesystemWatcher(
        watch_path=str(tmp_path),
        patterns=["*.py"],
        callback=on_event,
        debounce_seconds=0.1,
    )
    await watcher.start()
    try:
        (tmp_path / "test.py").write_text("print('hello')")
        await asyncio.sleep(0.5)

        assert len(events) >= 1
        assert events[0].event_type == EventType.FILESYSTEM
        assert "test.py" in events[0].payload["path"]
    finally:
        await watcher.stop()


async def test_filesystem_watcher_ignores_non_matching_files(tmp_path):
    events: list[ObservationEvent] = []

    async def on_event(event: ObservationEvent):
        events.append(event)

    watcher = FilesystemWatcher(
        watch_path=str(tmp_path),
        patterns=["*.py"],
        callback=on_event,
        debounce_seconds=0.1,
    )
    await watcher.start()
    try:
        (tmp_path / "readme.txt").write_text("hello")
        await asyncio.sleep(0.5)
        assert len(events) == 0
    finally:
        await watcher.stop()


async def test_filesystem_watcher_debounces(tmp_path):
    events: list[ObservationEvent] = []

    async def on_event(event: ObservationEvent):
        events.append(event)

    watcher = FilesystemWatcher(
        watch_path=str(tmp_path),
        patterns=["*.py"],
        callback=on_event,
        debounce_seconds=0.3,
    )
    await watcher.start()
    try:
        for i in range(5):
            (tmp_path / "test.py").write_text(f"v{i}")
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.5)
        assert len(events) < 5  # debounced
    finally:
        await watcher.stop()
