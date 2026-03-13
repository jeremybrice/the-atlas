# ATLAS Phase 2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform ATLAS from a CLI-only tool into a background daemon that watches, reacts, learns, and creates its own skills.

**Architecture:** Daemon process with asyncio event loop, Unix socket for CLI communication, observation engine for filesystem/schedule triggers, reactive execution pipeline, Skill Forge for autonomous skill creation, and completed memory system with procedural tier and pattern extraction.

**Tech Stack:** Python 3.12+, asyncio, aiosqlite, anthropic SDK, watchdog (filesystem monitoring), click (CLI)

---

## Task 1: Phase 2 Contract Types

Add new dataclasses and enums to the shared contracts for Phase 2 features.

**Files:**
- Modify: `src/atlas/contracts/types.py`
- Test: `tests/unit/contracts/test_types.py`

**Step 1: Write failing tests**

```python
# Append to tests/unit/contracts/test_types.py

from atlas.contracts.types import (
    ObservationEvent, EventType, Procedure, DaemonCommand, DaemonResponse,
)

def test_observation_event_creation():
    event = ObservationEvent(
        event_type=EventType.FILESYSTEM,
        source="watch:src/**/*.py",
        payload={"path": "src/main.py", "action": "modified"},
    )
    assert event.event_id  # auto-generated
    assert event.priority == 5

def test_procedure_creation():
    proc = Procedure(
        name="run-tests",
        description="Run pytest after source change",
        trigger_pattern="filesystem:src/**/*.py",
        steps=[{"skill": "shell.execute", "params": {"command": "pytest"}}],
    )
    assert proc.procedure_id  # auto-generated
    assert proc.success_rate == 0.0

def test_daemon_command_and_response():
    cmd = DaemonCommand(command="goal", payload={"goal_text": "do thing"})
    assert cmd.command_id  # auto-generated
    resp = DaemonResponse(command_id=cmd.command_id, status="ok", payload={"mission_id": "abc"})
    assert resp.status == "ok"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/contracts/test_types.py -v -k "observation or procedure or daemon"`
Expected: ImportError — names not defined yet

**Step 3: Implement the new types**

Add to `src/atlas/contracts/types.py` after existing code:

```python
class EventType(str, Enum):
    FILESYSTEM = "filesystem"
    SCHEDULED = "scheduled"
    GOAL = "goal"

@dataclass
class ObservationEvent:
    event_type: EventType
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=new_id)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    priority: int = 5

@dataclass
class Procedure:
    name: str
    description: str
    trigger_pattern: str
    steps: list[dict[str, Any]]
    procedure_id: str = field(default_factory=new_id)
    success_rate: float = 0.0
    use_count: int = 0
    last_used: str = ""
    created_from: str = ""

@dataclass
class DaemonCommand:
    command: str
    payload: dict[str, Any] = field(default_factory=dict)
    command_id: str = field(default_factory=new_id)

@dataclass
class DaemonResponse:
    command_id: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
```

Add required imports at top: `from datetime import datetime, timezone`.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/contracts/test_types.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/contracts/types.py tests/unit/contracts/test_types.py
git commit -m "feat: add Phase 2 contract types — ObservationEvent, Procedure, DaemonCommand"
```

---

## Task 2: Daemon Socket Protocol

Build the Unix socket server and client for daemon <-> CLI communication.

**Files:**
- Create: `src/atlas/daemon/__init__.py`
- Create: `src/atlas/daemon/protocol.py`
- Test: `tests/unit/daemon/test_protocol.py`
- Test: `tests/unit/daemon/__init__.py`

**Step 1: Write failing tests**

```python
# tests/unit/daemon/test_protocol.py
import json
import pytest
from atlas.daemon.protocol import encode_message, decode_message, DaemonSocketServer, DaemonSocketClient
from atlas.contracts.types import DaemonCommand, DaemonResponse

def test_encode_decode_command():
    cmd = DaemonCommand(command="goal", payload={"goal_text": "test"})
    encoded = encode_message(cmd)
    decoded = decode_message(encoded)
    assert decoded["command"] == "goal"
    assert decoded["payload"]["goal_text"] == "test"

def test_encode_decode_response():
    resp = DaemonResponse(command_id="abc", status="ok", payload={"result": "done"})
    encoded = encode_message(resp)
    decoded = decode_message(encoded)
    assert decoded["status"] == "ok"

async def test_server_client_roundtrip(tmp_path):
    socket_path = str(tmp_path / "test.sock")
    responses = []

    async def handler(data: dict) -> dict:
        return {"command_id": data["command_id"], "status": "ok", "payload": {"echo": data["command"]}}

    server = DaemonSocketServer(socket_path, handler)
    await server.start()
    try:
        client = DaemonSocketClient(socket_path)
        resp = await client.send(DaemonCommand(command="ping"))
        assert resp["status"] == "ok"
        assert resp["payload"]["echo"] == "ping"
    finally:
        await server.stop()
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/daemon/test_protocol.py -v`
Expected: ImportError

**Step 3: Implement protocol**

`src/atlas/daemon/protocol.py`:

```python
"""Daemon socket protocol — JSON-over-Unix-socket with length prefix."""

from __future__ import annotations

import asyncio
import json
import logging
import struct
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

HEADER_FORMAT = "!I"  # 4-byte unsigned int, network byte order
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


def encode_message(obj: Any) -> bytes:
    data = json.dumps(asdict(obj) if hasattr(obj, "__dataclass_fields__") else obj).encode()
    return struct.pack(HEADER_FORMAT, len(data)) + data


def decode_message(data: bytes) -> dict:
    return json.loads(data)


async def _read_message(reader: asyncio.StreamReader) -> dict | None:
    header = await reader.readexactly(HEADER_SIZE)
    (length,) = struct.unpack(HEADER_FORMAT, header)
    payload = await reader.readexactly(length)
    return json.loads(payload)


async def _write_message(writer: asyncio.StreamWriter, data: dict) -> None:
    encoded = json.dumps(data).encode()
    writer.write(struct.pack(HEADER_FORMAT, len(encoded)) + encoded)
    await writer.drain()


class DaemonSocketServer:
    def __init__(self, socket_path: str, handler: Callable[[dict], Coroutine[Any, Any, dict]]):
        self._socket_path = socket_path
        self._handler = handler
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        Path(self._socket_path).unlink(missing_ok=True)
        self._server = await asyncio.start_unix_server(self._handle_client, path=self._socket_path)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        Path(self._socket_path).unlink(missing_ok=True)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await _read_message(reader)
            if request:
                response = await self._handler(request)
                await _write_message(writer, response)
        except Exception as e:
            logger.error("Socket handler error: %s", e)
        finally:
            writer.close()
            await writer.wait_closed()


class DaemonSocketClient:
    def __init__(self, socket_path: str):
        self._socket_path = socket_path

    async def send(self, command: Any) -> dict:
        reader, writer = await asyncio.open_unix_connection(self._socket_path)
        try:
            encoded = json.dumps(asdict(command) if hasattr(command, "__dataclass_fields__") else command).encode()
            writer.write(struct.pack(HEADER_FORMAT, len(encoded)) + encoded)
            await writer.drain()
            response = await _read_message(reader)
            return response
        finally:
            writer.close()
            await writer.wait_closed()
```

**Step 4: Run tests**

Run: `pytest tests/unit/daemon/test_protocol.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/daemon/ tests/unit/daemon/
git commit -m "feat: add daemon socket protocol — length-prefixed JSON over Unix socket"
```

---

## Task 3: Daemon Process Manager

PID file management, daemon start/stop lifecycle, signal handling.

**Files:**
- Create: `src/atlas/daemon/manager.py`
- Test: `tests/unit/daemon/test_manager.py`

**Step 1: Write failing tests**

```python
# tests/unit/daemon/test_manager.py
import os
import signal
from pathlib import Path
import pytest
from atlas.daemon.manager import PidFile

def test_pidfile_write_and_read(tmp_path):
    pf = PidFile(str(tmp_path / "test.pid"))
    pf.write(12345)
    assert pf.read() == 12345
    assert pf.is_running() is False  # PID 12345 unlikely to exist

def test_pidfile_remove(tmp_path):
    pf = PidFile(str(tmp_path / "test.pid"))
    pf.write(os.getpid())
    assert pf.read() == os.getpid()
    pf.remove()
    assert pf.read() is None

def test_pidfile_stale_detection(tmp_path):
    pf = PidFile(str(tmp_path / "test.pid"))
    pf.write(99999999)  # non-existent PID
    assert pf.is_running() is False
    assert pf.read() is None  # auto-cleaned stale PID

def test_pidfile_current_process(tmp_path):
    pf = PidFile(str(tmp_path / "test.pid"))
    pf.write(os.getpid())
    assert pf.is_running() is True
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/daemon/test_manager.py -v`
Expected: ImportError

**Step 3: Implement PidFile**

`src/atlas/daemon/manager.py`:

```python
"""Daemon process management — PID file and lifecycle."""

from __future__ import annotations

import os
import signal
from pathlib import Path


class PidFile:
    def __init__(self, path: str):
        self._path = Path(path)

    def write(self, pid: int) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(str(pid))

    def read(self) -> int | None:
        if not self._path.exists():
            return None
        try:
            pid = int(self._path.read_text().strip())
        except (ValueError, OSError):
            self.remove()
            return None
        # Check if PID is still alive
        if not _pid_exists(pid):
            self.remove()
            return None
        return pid

    def is_running(self) -> bool:
        return self.read() is not None

    def remove(self) -> None:
        self._path.unlink(missing_ok=True)


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but we can't signal it
```

**Step 4: Run tests**

Run: `pytest tests/unit/daemon/test_manager.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/daemon/manager.py tests/unit/daemon/test_manager.py
git commit -m "feat: add PID file management for daemon lifecycle"
```

---

## Task 4: Daemon Main Loop and CLI Commands

Wire the daemon into the CLI with `atlas daemon start/stop/status`.

**Files:**
- Create: `src/atlas/daemon/loop.py`
- Modify: `src/atlas/cli.py`
- Test: `tests/unit/daemon/test_daemon_loop.py`

**Step 1: Write failing tests**

```python
# tests/unit/daemon/test_daemon_loop.py
import asyncio
import pytest
from unittest.mock import AsyncMock
from atlas.daemon.loop import DaemonLoop
from atlas.contracts.types import DaemonCommand

async def test_daemon_loop_handles_goal_command(tmp_path):
    socket_path = str(tmp_path / "test.sock")
    pid_path = str(tmp_path / "test.pid")

    executor = AsyncMock(return_value={"status": "completed", "tasks": 3})

    loop = DaemonLoop(
        socket_path=socket_path,
        pid_path=pid_path,
        goal_executor=executor,
    )

    # Start daemon in background
    task = asyncio.create_task(loop.start())
    await asyncio.sleep(0.1)  # let it start

    try:
        from atlas.daemon.protocol import DaemonSocketClient
        client = DaemonSocketClient(socket_path)
        resp = await client.send(DaemonCommand(command="goal", payload={"goal_text": "test goal"}))
        assert resp["status"] == "ok"
        executor.assert_called_once()
    finally:
        await loop.stop()
        await task

async def test_daemon_loop_status_command(tmp_path):
    socket_path = str(tmp_path / "test.sock")
    pid_path = str(tmp_path / "test.pid")
    executor = AsyncMock()

    loop = DaemonLoop(socket_path=socket_path, pid_path=pid_path, goal_executor=executor)
    task = asyncio.create_task(loop.start())
    await asyncio.sleep(0.1)

    try:
        from atlas.daemon.protocol import DaemonSocketClient
        client = DaemonSocketClient(socket_path)
        resp = await client.send(DaemonCommand(command="status"))
        assert resp["status"] == "ok"
        assert "uptime_seconds" in resp["payload"]
    finally:
        await loop.stop()
        await task

async def test_daemon_loop_shutdown_command(tmp_path):
    socket_path = str(tmp_path / "test.sock")
    pid_path = str(tmp_path / "test.pid")
    executor = AsyncMock()

    loop = DaemonLoop(socket_path=socket_path, pid_path=pid_path, goal_executor=executor)
    task = asyncio.create_task(loop.start())
    await asyncio.sleep(0.1)

    from atlas.daemon.protocol import DaemonSocketClient
    client = DaemonSocketClient(socket_path)
    resp = await client.send(DaemonCommand(command="shutdown"))
    assert resp["status"] == "ok"

    await task  # should exit cleanly
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/daemon/test_daemon_loop.py -v`
Expected: ImportError

**Step 3: Implement DaemonLoop**

`src/atlas/daemon/loop.py`:

```python
"""Daemon main loop — runs the socket server and dispatches commands."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Callable, Coroutine

from atlas.daemon.manager import PidFile
from atlas.daemon.protocol import DaemonSocketServer

logger = logging.getLogger(__name__)


class DaemonLoop:
    def __init__(
        self,
        socket_path: str,
        pid_path: str,
        goal_executor: Callable[..., Coroutine[Any, Any, dict]] | None = None,
    ):
        self._socket_path = socket_path
        self._pid_file = PidFile(pid_path)
        self._goal_executor = goal_executor
        self._server: DaemonSocketServer | None = None
        self._running = False
        self._start_time = 0.0

    async def start(self) -> None:
        self._start_time = time.monotonic()
        self._running = True
        self._pid_file.write(os.getpid())

        self._server = DaemonSocketServer(self._socket_path, self._handle_command)
        await self._server.start()
        logger.info("Daemon started. PID=%d socket=%s", os.getpid(), self._socket_path)

        while self._running:
            await asyncio.sleep(0.1)

        await self._server.stop()
        self._pid_file.remove()
        logger.info("Daemon stopped.")

    async def stop(self) -> None:
        self._running = False

    async def _handle_command(self, data: dict) -> dict:
        command = data.get("command", "")
        command_id = data.get("command_id", "")

        match command:
            case "goal":
                return await self._handle_goal(command_id, data.get("payload", {}))
            case "status":
                return self._handle_status(command_id)
            case "shutdown":
                asyncio.get_event_loop().call_soon(asyncio.ensure_future, self.stop())
                return {"command_id": command_id, "status": "ok", "payload": {"message": "shutting down"}}
            case _:
                return {"command_id": command_id, "status": "error", "error": f"unknown command: {command}"}

    async def _handle_goal(self, command_id: str, payload: dict) -> dict:
        if not self._goal_executor:
            return {"command_id": command_id, "status": "error", "error": "no goal executor configured"}
        try:
            result = await self._goal_executor(payload.get("goal_text", ""))
            return {"command_id": command_id, "status": "ok", "payload": result}
        except Exception as e:
            return {"command_id": command_id, "status": "error", "error": str(e)}

    def _handle_status(self, command_id: str) -> dict:
        uptime = time.monotonic() - self._start_time
        return {
            "command_id": command_id,
            "status": "ok",
            "payload": {
                "pid": os.getpid(),
                "uptime_seconds": round(uptime, 1),
                "running": self._running,
            },
        }
```

**Step 4: Run tests**

Run: `pytest tests/unit/daemon/test_daemon_loop.py -v`
Expected: All PASS

**Step 5: Add CLI commands**

Add to `src/atlas/cli.py` — new `daemon` command group with `start`, `stop`, `status` subcommands. The `start` command forks a background process, `stop` sends shutdown via socket, `status` queries the daemon. Update `atlas goal` to detect a running daemon and forward via socket client.

**Step 6: Commit**

```bash
git add src/atlas/daemon/loop.py tests/unit/daemon/test_daemon_loop.py src/atlas/cli.py
git commit -m "feat: add daemon main loop with goal/status/shutdown commands and CLI integration"
```

---

## Task 5: Observation Engine — Filesystem Watcher

Watch filesystem for changes using `watchdog`, emit `ObservationEvent`s.

**Files:**
- Create: `src/atlas/observation/__init__.py`
- Create: `src/atlas/observation/watcher.py`
- Test: `tests/unit/observation/__init__.py`
- Test: `tests/unit/observation/test_watcher.py`
- Modify: `pyproject.toml` (add watchdog dependency)

**Step 1: Add watchdog dependency**

In `pyproject.toml`, add `"watchdog>=4.0"` to `dependencies`.

Run: `pip install -e ".[dev]"`

**Step 2: Write failing tests**

```python
# tests/unit/observation/test_watcher.py
import asyncio
from pathlib import Path
import pytest
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
        # Create a file
        (tmp_path / "test.py").write_text("print('hello')")
        await asyncio.sleep(0.5)  # wait for debounce

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
        # Rapid writes should debounce into fewer events
        for i in range(5):
            (tmp_path / "test.py").write_text(f"v{i}")
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.5)
        assert len(events) < 5  # debounced
    finally:
        await watcher.stop()
```

**Step 3: Run to verify failure**

Run: `pytest tests/unit/observation/test_watcher.py -v`
Expected: ImportError

**Step 4: Implement FilesystemWatcher**

`src/atlas/observation/watcher.py`:

```python
"""Filesystem watcher — monitors file changes and emits ObservationEvents."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
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
        handler = _WatchdogHandler(self._on_raw_event, self._patterns)
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
    def __init__(self, callback, patterns):
        self._callback = callback
        self._patterns = patterns

    def on_any_event(self, event: FileSystemEvent):
        if event.is_directory:
            return
        path = event.src_path
        if any(fnmatch.fnmatch(Path(path).name, p) for p in self._patterns):
            self._callback(path, event.event_type)
```

**Step 5: Run tests**

Run: `pytest tests/unit/observation/test_watcher.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add pyproject.toml src/atlas/observation/ tests/unit/observation/
git commit -m "feat: add filesystem watcher with debouncing and pattern matching"
```

---

## Task 6: Observation Engine — Scheduled Triggers

Cron-like scheduled triggers that fire on intervals.

**Files:**
- Create: `src/atlas/observation/scheduler.py`
- Test: `tests/unit/observation/test_scheduler.py`

**Step 1: Write failing tests**

```python
# tests/unit/observation/test_scheduler.py
import asyncio
import pytest
from atlas.observation.scheduler import ScheduledTrigger
from atlas.contracts.types import ObservationEvent, EventType

async def test_scheduled_trigger_fires_on_interval():
    events: list[ObservationEvent] = []

    async def on_event(event: ObservationEvent):
        events.append(event)

    trigger = ScheduledTrigger(
        name="test-trigger",
        interval_seconds=0.2,
        goal_template="do the thing",
        callback=on_event,
    )
    await trigger.start()
    await asyncio.sleep(0.5)
    await trigger.stop()

    assert len(events) >= 2
    assert events[0].event_type == EventType.SCHEDULED
    assert events[0].source == "schedule:test-trigger"
    assert events[0].payload["goal"] == "do the thing"

async def test_scheduled_trigger_stop():
    events: list[ObservationEvent] = []

    async def on_event(event: ObservationEvent):
        events.append(event)

    trigger = ScheduledTrigger(
        name="stop-test", interval_seconds=0.1, goal_template="x", callback=on_event,
    )
    await trigger.start()
    await asyncio.sleep(0.25)
    await trigger.stop()
    count_at_stop = len(events)
    await asyncio.sleep(0.3)
    assert len(events) == count_at_stop  # no more events after stop
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/observation/test_scheduler.py -v`
Expected: ImportError

**Step 3: Implement ScheduledTrigger**

`src/atlas/observation/scheduler.py`:

```python
"""Scheduled trigger — fires ObservationEvents on a recurring interval."""

from __future__ import annotations

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
```

**Step 4: Run tests**

Run: `pytest tests/unit/observation/test_scheduler.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/observation/scheduler.py tests/unit/observation/test_scheduler.py
git commit -m "feat: add scheduled trigger for recurring observation events"
```

---

## Task 7: Priority Task Queue

Replace FIFO TaskQueue with priority-based queue that supports deduplication and concurrency limits.

**Files:**
- Modify: `src/atlas/core/tasks.py`
- Modify: `tests/unit/core/test_tasks.py`

**Step 1: Write failing tests**

```python
# Append to tests/unit/core/test_tasks.py

def test_priority_queue_ordering():
    q = TaskQueue()
    low = Task(description="low priority", priority=10)
    high = Task(description="high priority", priority=1)
    q.enqueue(low)
    q.enqueue(high)
    next_task = q.get_next()
    assert next_task.description == "high priority"

def test_task_deduplication():
    q = TaskQueue()
    q.enqueue(Task(description="run tests", dedup_key="tests"))
    q.enqueue(Task(description="run tests again", dedup_key="tests"))
    assert q.size() == 1  # second one was dropped

def test_task_dedup_different_keys():
    q = TaskQueue()
    q.enqueue(Task(description="run tests", dedup_key="tests"))
    q.enqueue(Task(description="run lint", dedup_key="lint"))
    assert q.size() == 2
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/core/test_tasks.py -v -k "priority or dedup"`
Expected: TypeError — Task doesn't accept `priority` or `dedup_key`

**Step 3: Implement**

Add `priority: int = 5` and `dedup_key: str = ""` fields to the `Task` dataclass in `src/atlas/core/tasks.py`.

Update `TaskQueue`:
- `enqueue()`: check `dedup_key` against pending tasks, skip if duplicate; insert maintaining priority order (lower number = higher priority)
- `get_next()`: return lowest-priority-number pending task

**Step 4: Run tests**

Run: `pytest tests/unit/core/test_tasks.py -v`
Expected: All PASS (existing + new)

**Step 5: Commit**

```bash
git add src/atlas/core/tasks.py tests/unit/core/test_tasks.py
git commit -m "feat: upgrade TaskQueue with priority ordering and deduplication"
```

---

## Task 8: Event Router — Rule Matching

Match observation events against configured rules and generate goals.

**Files:**
- Create: `src/atlas/observation/router.py`
- Test: `tests/unit/observation/test_router.py`

**Step 1: Write failing tests**

```python
# tests/unit/observation/test_router.py
import pytest
from atlas.observation.router import EventRouter, ReactiveRule
from atlas.contracts.types import ObservationEvent, EventType

def test_router_matches_filesystem_event():
    rule = ReactiveRule(
        name="test-on-change",
        event_type=EventType.FILESYSTEM,
        source_pattern="*.py",
        goal_template="Run tests for {path}",
        cooldown_seconds=0,
    )
    router = EventRouter(rules=[rule])
    event = ObservationEvent(
        event_type=EventType.FILESYSTEM,
        source="watch:/project",
        payload={"path": "/project/src/main.py", "action": "modified"},
    )
    goals = router.match(event)
    assert len(goals) == 1
    assert "main.py" in goals[0]

def test_router_respects_cooldown():
    rule = ReactiveRule(
        name="test",
        event_type=EventType.FILESYSTEM,
        source_pattern="*.py",
        goal_template="test",
        cooldown_seconds=60,
    )
    router = EventRouter(rules=[rule])
    event = ObservationEvent(
        event_type=EventType.FILESYSTEM,
        source="watch:/project",
        payload={"path": "main.py"},
    )
    goals1 = router.match(event)
    goals2 = router.match(event)  # within cooldown
    assert len(goals1) == 1
    assert len(goals2) == 0

def test_router_no_match_wrong_event_type():
    rule = ReactiveRule(
        name="test",
        event_type=EventType.SCHEDULED,
        source_pattern="*",
        goal_template="test",
        cooldown_seconds=0,
    )
    router = EventRouter(rules=[rule])
    event = ObservationEvent(
        event_type=EventType.FILESYSTEM,
        source="watch:/project",
        payload={"path": "main.py"},
    )
    assert router.match(event) == []
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/observation/test_router.py -v`
Expected: ImportError

**Step 3: Implement EventRouter**

`src/atlas/observation/router.py`:

```python
"""Event Router — matches observation events to reactive rules."""

from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass, field

from atlas.contracts.types import EventType, ObservationEvent


@dataclass
class ReactiveRule:
    name: str
    event_type: EventType
    source_pattern: str
    goal_template: str
    cooldown_seconds: float = 60.0


class EventRouter:
    def __init__(self, rules: list[ReactiveRule] | None = None):
        self._rules = rules or []
        self._last_fired: dict[str, float] = {}

    def add_rule(self, rule: ReactiveRule) -> None:
        self._rules.append(rule)

    def match(self, event: ObservationEvent) -> list[str]:
        goals = []
        now = time.monotonic()
        for rule in self._rules:
            if rule.event_type != event.event_type:
                continue
            path = event.payload.get("path", "")
            if not fnmatch.fnmatch(path, rule.source_pattern) and rule.source_pattern != "*":
                # Also check just the filename
                if not fnmatch.fnmatch(path.rsplit("/", 1)[-1], rule.source_pattern):
                    continue
            # Cooldown check
            last = self._last_fired.get(rule.name, 0)
            if now - last < rule.cooldown_seconds:
                continue
            self._last_fired[rule.name] = now
            # Template substitution
            goal = rule.goal_template.format(**event.payload)
            goals.append(goal)
        return goals
```

**Step 4: Run tests**

Run: `pytest tests/unit/observation/test_router.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/observation/router.py tests/unit/observation/test_router.py
git commit -m "feat: add event router with rule matching and cooldown"
```

---

## Task 9: Reactive Execution Loop

Integrate observation engine + event router into the daemon loop so events trigger autonomous goal execution.

**Files:**
- Modify: `src/atlas/daemon/loop.py`
- Create: `src/atlas/observation/engine.py`
- Test: `tests/integration/test_reactive.py`

**Step 1: Write failing integration test**

```python
# tests/integration/test_reactive.py
import asyncio
from pathlib import Path
import pytest
from atlas.observation.engine import ObservationEngine
from atlas.observation.router import EventRouter, ReactiveRule
from atlas.contracts.types import EventType

async def test_file_change_triggers_goal(tmp_path):
    goals_received: list[str] = []

    async def goal_handler(goal_text: str) -> dict:
        goals_received.append(goal_text)
        return {"status": "completed"}

    rule = ReactiveRule(
        name="test-on-change",
        event_type=EventType.FILESYSTEM,
        source_pattern="*.py",
        goal_template="Run tests for {path}",
        cooldown_seconds=0,
    )
    router = EventRouter(rules=[rule])
    engine = ObservationEngine(router=router, goal_handler=goal_handler)

    engine.add_filesystem_watch(str(tmp_path), ["*.py"], debounce_seconds=0.1)
    await engine.start()
    try:
        (tmp_path / "app.py").write_text("x = 1")
        await asyncio.sleep(0.5)
        assert len(goals_received) >= 1
        assert "app.py" in goals_received[0]
    finally:
        await engine.stop()
```

**Step 2: Run to verify failure**

Run: `pytest tests/integration/test_reactive.py -v`
Expected: ImportError

**Step 3: Implement ObservationEngine**

`src/atlas/observation/engine.py`:

```python
"""Observation Engine — coordinates watchers, schedulers, and the event router."""

from __future__ import annotations

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
            callback=self._on_event,
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
            callback=self._on_event,
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

    async def _on_event(self, event: ObservationEvent) -> None:
        goals = self._router.match(event)
        for goal in goals:
            logger.info("Reactive goal triggered: %s (from %s)", goal, event.source)
            try:
                await self._goal_handler(goal)
            except Exception as e:
                logger.error("Goal execution failed: %s", e)
```

**Step 4: Run tests**

Run: `pytest tests/integration/test_reactive.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/observation/engine.py tests/integration/test_reactive.py
git commit -m "feat: add observation engine coordinating watchers, schedulers, and event router"
```

---

## Task 10: Replanning on Failure

When a task fails during execution, ask Claude to replan with error context.

**Files:**
- Modify: `src/atlas/core/loop.py`
- Test: `tests/unit/core/test_replan.py`

**Step 1: Write failing tests**

```python
# tests/unit/core/test_replan.py
import pytest
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
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/core/test_replan.py -v`
Expected: ImportError

**Step 3: Implement**

Add `build_replan_prompt()` function to `src/atlas/core/loop.py`:

```python
def build_replan_prompt(
    original_goal: str,
    failed_task_desc: str,
    error: str,
    remaining_tasks: list[str],
    skills: str,
    context: str,
) -> str:
    remaining = ", ".join(remaining_tasks) if remaining_tasks else "none"
    return (
        f"A task failed during execution. Replan the remaining work. "
        f"Original goal: {original_goal}. "
        f"Failed task: {failed_task_desc}. Error: {error}. "
        f"Remaining tasks that were planned: {remaining}. "
        f"Available skills: {skills}. Project context: {context}. "
        f'Respond with ONLY JSON: {{"tasks":[{{"description":"...","skill":"skill.id","params":{{}}}}]}}'
    )
```

Then update `execute_mission()` in `ExecutionLoop` to call replan when a task fails:
- After a task fails, if `max_replans > 0`, call `claude_oneshot(build_replan_prompt(...))` to get new tasks
- Parse new tasks and append to remaining queue
- Decrement replan counter
- If replan also fails, continue to next task (don't abort mission)

Add `environment` and `max_replans=2` parameters to `ExecutionLoop.__init__`.

**Step 4: Run tests**

Run: `pytest tests/unit/core/test_replan.py tests/unit/core/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/core/loop.py tests/unit/core/test_replan.py
git commit -m "feat: add replanning on task failure with error context"
```

---

## Task 11: Procedural Memory Store

New memory tier that stores learned workflows (procedures).

**Files:**
- Create: `src/atlas/memory/procedural.py`
- Modify: `src/atlas/memory/store.py` (add table)
- Test: `tests/unit/memory/test_procedural.py`

**Step 1: Write failing tests**

```python
# tests/unit/memory/test_procedural.py
import pytest
from atlas.memory.procedural import ProceduralMemoryStore
from atlas.memory.store import DatabaseStore
from atlas.contracts.types import Procedure

@pytest.fixture
async def proc_store(tmp_path):
    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()
    store = ProceduralMemoryStore(db)
    await store.initialize()
    yield store
    await db.close()

async def test_store_and_retrieve(proc_store):
    proc = Procedure(
        name="run-tests",
        description="Run pytest after source change",
        trigger_pattern="filesystem:*.py",
        steps=[{"skill": "shell.execute", "params": {"command": "pytest"}}],
    )
    proc_id = await proc_store.store(proc)
    retrieved = await proc_store.get(proc_id)
    assert retrieved is not None
    assert retrieved.name == "run-tests"
    assert len(retrieved.steps) == 1

async def test_search_by_trigger(proc_store):
    await proc_store.store(Procedure(
        name="test-py", description="test", trigger_pattern="filesystem:*.py",
        steps=[{"skill": "shell.execute", "params": {"command": "pytest"}}],
    ))
    await proc_store.store(Procedure(
        name="lint-js", description="lint", trigger_pattern="filesystem:*.js",
        steps=[{"skill": "shell.execute", "params": {"command": "eslint"}}],
    ))
    results = await proc_store.search_by_trigger("filesystem:*.py")
    assert len(results) == 1
    assert results[0].name == "test-py"

async def test_update_success_rate(proc_store):
    proc = Procedure(
        name="test", description="test", trigger_pattern="*",
        steps=[], success_rate=0.0, use_count=0,
    )
    proc_id = await proc_store.store(proc)
    await proc_store.record_outcome(proc_id, success=True)
    await proc_store.record_outcome(proc_id, success=False)
    updated = await proc_store.get(proc_id)
    assert updated.use_count == 2
    assert updated.success_rate == 0.5
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/memory/test_procedural.py -v`
Expected: ImportError

**Step 3: Implement ProceduralMemoryStore**

`src/atlas/memory/procedural.py`:

```python
"""Procedural Memory — stores and retrieves learned workflow procedures."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from atlas.contracts.types import Procedure
from atlas.memory.store import DatabaseStore


class ProceduralMemoryStore:
    def __init__(self, db: DatabaseStore):
        self._db = db

    async def initialize(self) -> None:
        await self._db.db.execute("""
            CREATE TABLE IF NOT EXISTS procedures (
                procedure_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                trigger_pattern TEXT,
                steps TEXT,
                success_rate REAL DEFAULT 0.0,
                use_count INTEGER DEFAULT 0,
                last_used TEXT,
                created_from TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self._db.db.commit()

    async def store(self, proc: Procedure) -> str:
        await self._db.db.execute(
            "INSERT INTO procedures (procedure_id, name, description, trigger_pattern, steps, success_rate, use_count, last_used, created_from) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (proc.procedure_id, proc.name, proc.description, proc.trigger_pattern,
             json.dumps(proc.steps), proc.success_rate, proc.use_count, proc.last_used, proc.created_from),
        )
        await self._db.db.commit()
        return proc.procedure_id

    async def get(self, procedure_id: str) -> Procedure | None:
        cursor = await self._db.db.execute(
            "SELECT * FROM procedures WHERE procedure_id = ?", (procedure_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_procedure(row)

    async def search_by_trigger(self, pattern: str) -> list[Procedure]:
        cursor = await self._db.db.execute(
            "SELECT * FROM procedures WHERE trigger_pattern = ? ORDER BY success_rate DESC",
            (pattern,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_procedure(r) for r in rows]

    async def record_outcome(self, procedure_id: str, success: bool) -> None:
        proc = await self.get(procedure_id)
        if not proc:
            return
        new_count = proc.use_count + 1
        total_successes = round(proc.success_rate * proc.use_count) + (1 if success else 0)
        new_rate = total_successes / new_count
        now = datetime.now(timezone.utc).isoformat()
        await self._db.db.execute(
            "UPDATE procedures SET success_rate = ?, use_count = ?, last_used = ? WHERE procedure_id = ?",
            (new_rate, new_count, now, procedure_id),
        )
        await self._db.db.commit()

    async def list_all(self) -> list[Procedure]:
        cursor = await self._db.db.execute("SELECT * FROM procedures ORDER BY use_count DESC")
        rows = await cursor.fetchall()
        return [self._row_to_procedure(r) for r in rows]

    def _row_to_procedure(self, row) -> Procedure:
        return Procedure(
            procedure_id=row[0],
            name=row[1],
            description=row[2] or "",
            trigger_pattern=row[3] or "",
            steps=json.loads(row[4]) if row[4] else [],
            success_rate=row[5] or 0.0,
            use_count=row[6] or 0,
            last_used=row[7] or "",
            created_from=row[8] or "",
        )
```

**Step 4: Run tests**

Run: `pytest tests/unit/memory/test_procedural.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/memory/procedural.py tests/unit/memory/test_procedural.py
git commit -m "feat: add procedural memory store for learned workflows"
```

---

## Task 12: Purpose-Aware Context Assembly

Upgrade ContextAssembler with different ranking strategies per purpose.

**Files:**
- Modify: `src/atlas/memory/retrieval.py`
- Modify: `tests/unit/memory/test_retrieval.py`

**Step 1: Write failing tests**

```python
# Append to tests/unit/memory/test_retrieval.py
from atlas.contracts.types import Procedure

def test_assemble_planning_context_includes_procedures():
    assembler = ContextAssembler()
    episodes = [
        Episode(episode_type=EpisodeType.TASK_EXECUTION, trigger="run tests", outcome="completed"),
    ]
    procedures = [
        Procedure(name="run-tests", description="pytest after change",
                  trigger_pattern="filesystem:*.py",
                  steps=[{"skill": "shell.execute", "params": {"command": "pytest"}}]),
    ]
    query = ContextQuery(purpose="planning", task_description="run tests on changed files", token_budget=4000)
    bundle = assembler.assemble(query, episodes, procedures=procedures)
    assert any("run-tests" in c for c in bundle.contents)

def test_assemble_reflection_context_prioritizes_failures():
    assembler = ContextAssembler()
    success_ep = Episode(episode_type=EpisodeType.TASK_EXECUTION, trigger="task A", outcome="completed")
    failure_ep = Episode(episode_type=EpisodeType.TASK_EXECUTION, trigger="task B", outcome="failed",
                         lessons=["don't do X"])
    query = ContextQuery(purpose="reflection", task_description="analyze recent work", token_budget=500)
    bundle = assembler.assemble(query, [success_ep, failure_ep])
    # Failure episode should appear first in reflection context
    assert "failed" in bundle.contents[0].lower() or "don't do X" in bundle.contents[0]
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/memory/test_retrieval.py -v -k "planning_context or reflection"`
Expected: TypeError — `assemble()` doesn't accept `procedures` kwarg

**Step 3: Implement**

Update `ContextAssembler.assemble()` signature to accept optional `procedures: list[Procedure] = None` and `purpose` from the query:
- `purpose="planning"`: include procedure summaries, prioritize recent similar episodes
- `purpose="reflection"`: sort failed episodes before successful ones
- `purpose="forge"`: prioritize skill-creation episodes
- Default: existing recency-based behavior

**Step 4: Run tests**

Run: `pytest tests/unit/memory/test_retrieval.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/memory/retrieval.py tests/unit/memory/test_retrieval.py
git commit -m "feat: add purpose-aware context assembly with procedure support"
```

---

## Task 13: Skill Forge — Custom Skill Loader

Load user-created and forge-generated skills from `~/.atlas/skills/` directory.

**Files:**
- Create: `src/atlas/skills/loader.py`
- Test: `tests/unit/skills/test_loader.py`

**Step 1: Write failing tests**

```python
# tests/unit/skills/test_loader.py
import pytest
from pathlib import Path
from atlas.skills.loader import load_skills_from_directory
from atlas.skills.registry import SkillRegistry

def test_load_skill_from_file(tmp_path):
    skill_file = tmp_path / "greet.py"
    skill_file.write_text('''
SKILL_ID = "custom.greet"
SKILL_NAME = "Greet"
SKILL_DESCRIPTION = "Says hello"
SKILL_RISK = "low"

async def handler(params):
    name = params.get("name", "world")
    return {"greeting": f"hello {name}"}
''')
    registry = SkillRegistry()
    count = load_skills_from_directory(str(tmp_path), registry)
    assert count == 1
    desc = registry.get("custom.greet")
    assert desc.name == "Greet"
    assert desc.risk_level == "low"

def test_load_skips_invalid_files(tmp_path):
    (tmp_path / "bad.py").write_text("x = 1")  # missing SKILL_ID
    (tmp_path / "notpy.txt").write_text("SKILL_ID = 'x'")  # wrong extension
    registry = SkillRegistry()
    count = load_skills_from_directory(str(tmp_path), registry)
    assert count == 0

async def test_loaded_skill_is_invocable(tmp_path):
    skill_file = tmp_path / "echo.py"
    skill_file.write_text('''
SKILL_ID = "custom.echo"
SKILL_NAME = "Echo"
SKILL_DESCRIPTION = "Echoes input"
SKILL_RISK = "low"

async def handler(params):
    return {"echoed": params.get("text", "")}
''')
    registry = SkillRegistry()
    load_skills_from_directory(str(tmp_path), registry)
    from atlas.skills.runtime import InvocationRuntime
    runtime = InvocationRuntime(registry)
    result = await runtime.invoke("custom.echo", {"text": "hi"})
    assert result.status == "success"
    assert result.output["echoed"] == "hi"
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/skills/test_loader.py -v`
Expected: ImportError

**Step 3: Implement**

`src/atlas/skills/loader.py`:

```python
"""Skill Loader — loads custom skills from Python files in a directory."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from atlas.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

REQUIRED_ATTRS = ["SKILL_ID", "SKILL_NAME", "SKILL_DESCRIPTION", "SKILL_RISK", "handler"]


def load_skills_from_directory(directory: str, registry: SkillRegistry) -> int:
    skill_dir = Path(directory)
    if not skill_dir.is_dir():
        return 0

    count = 0
    for path in sorted(skill_dir.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(path.stem, path)
            if not spec or not spec.loader:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Validate required attributes
            if not all(hasattr(module, attr) for attr in REQUIRED_ATTRS):
                logger.debug("Skipping %s: missing required attributes", path.name)
                continue

            registry.register(
                skill_id=module.SKILL_ID,
                name=module.SKILL_NAME,
                description=module.SKILL_DESCRIPTION,
                handler=module.handler,
                risk_level=module.SKILL_RISK,
            )
            count += 1
            logger.info("Loaded skill: %s from %s", module.SKILL_ID, path.name)
        except Exception as e:
            logger.warning("Failed to load skill from %s: %s", path.name, e)

    return count
```

**Step 4: Run tests**

Run: `pytest tests/unit/skills/test_loader.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/skills/loader.py tests/unit/skills/test_loader.py
git commit -m "feat: add skill loader for custom .py skill files"
```

---

## Task 14: Skill Forge — Generation Pipeline

The core Forge: detect capability gaps, generate skills via Claude, test them, register.

**Files:**
- Create: `src/atlas/skills/forge.py`
- Test: `tests/unit/skills/test_forge.py`

**Step 1: Write failing tests**

```python
# tests/unit/skills/test_forge.py
import pytest
from unittest.mock import AsyncMock
from atlas.skills.forge import SkillForge, ForgeResult
from atlas.skills.registry import SkillRegistry
from atlas.contracts.types import ClaudeResponse

@pytest.fixture
def forge_env(tmp_path):
    registry = SkillRegistry()
    claude = AsyncMock()
    return {
        "registry": registry,
        "claude": claude,
        "skills_dir": str(tmp_path / "skills"),
        "workspace": str(tmp_path),
    }

async def test_forge_generates_skill(forge_env):
    # Mock Claude returning valid skill code
    skill_code = '''
SKILL_ID = "custom.count_lines"
SKILL_NAME = "Count Lines"
SKILL_DESCRIPTION = "Counts lines in a file"
SKILL_RISK = "low"

async def handler(params):
    path = params["path"]
    with open(path) as f:
        return {"count": len(f.readlines())}
'''
    forge_env["claude"].oneshot = AsyncMock(return_value=ClaudeResponse(
        content=skill_code, parsed_output=None
    ))

    forge = SkillForge(
        registry=forge_env["registry"],
        claude_bridge=forge_env["claude"],
        skills_dir=forge_env["skills_dir"],
        workspace=forge_env["workspace"],
    )
    result = await forge.create_skill(
        gap_description="I need to count lines in a file",
        context="working with text files",
    )
    assert result.success
    assert result.skill_id == "custom.count_lines"
    assert forge_env["registry"].get("custom.count_lines") is not None

async def test_forge_handles_invalid_code(forge_env):
    forge_env["claude"].oneshot = AsyncMock(return_value=ClaudeResponse(
        content="this is not valid python", parsed_output=None
    ))
    forge = SkillForge(
        registry=forge_env["registry"],
        claude_bridge=forge_env["claude"],
        skills_dir=forge_env["skills_dir"],
        workspace=forge_env["workspace"],
    )
    result = await forge.create_skill(gap_description="do something", context="")
    assert not result.success
    assert result.error
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/skills/test_forge.py -v`
Expected: ImportError

**Step 3: Implement SkillForge**

`src/atlas/skills/forge.py`:

```python
"""Skill Forge — generates new skills from capability gap descriptions."""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path

from atlas.contracts.types import ClaudeResponse
from atlas.env.claude import ClaudeCodeBridge
from atlas.skills.loader import REQUIRED_ATTRS
from atlas.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

FORGE_SYSTEM_PROMPT = (
    "You are a Python skill generator for the ATLAS agent system. "
    "Generate ONLY a valid Python module with these required module-level attributes: "
    "SKILL_ID (str), SKILL_NAME (str), SKILL_DESCRIPTION (str), SKILL_RISK (str: low/medium/high), "
    "and an async handler function: async def handler(params: dict) -> dict. "
    "Output ONLY the Python code, no markdown fences, no explanations."
)

FORGE_PROMPT_TEMPLATE = (
    "Create a Python skill module for this capability gap: {gap}. "
    "Context: {context}. "
    "The handler receives a params dict and must return a result dict. "
    "Use only Python standard library. Set SKILL_RISK to 'high' for safety. "
    "The SKILL_ID must start with 'custom.' prefix."
)


@dataclass
class ForgeResult:
    success: bool
    skill_id: str = ""
    file_path: str = ""
    error: str = ""


class SkillForge:
    def __init__(
        self,
        registry: SkillRegistry,
        claude_bridge: ClaudeCodeBridge,
        skills_dir: str,
        workspace: str,
        max_retries: int = 1,
    ):
        self._registry = registry
        self._claude = claude_bridge
        self._skills_dir = Path(skills_dir)
        self._workspace = workspace
        self._max_retries = max_retries

    async def create_skill(self, gap_description: str, context: str) -> ForgeResult:
        self._skills_dir.mkdir(parents=True, exist_ok=True)

        for attempt in range(1 + self._max_retries):
            prompt = FORGE_PROMPT_TEMPLATE.format(gap=gap_description, context=context)
            if attempt > 0:
                prompt += f" Previous attempt failed: {last_error}. Fix the issues."

            response = await self._claude.oneshot(prompt, system_prompt=FORGE_SYSTEM_PROMPT)
            code = self._extract_code(response.content)

            result = self._validate_and_register(code)
            if result.success:
                return result
            last_error = result.error

        return ForgeResult(success=False, error=f"Failed after {1 + self._max_retries} attempts: {last_error}")

    def _extract_code(self, content: str) -> str:
        # Strip markdown fences if present
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            lines = lines[1:]  # remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)
        return content

    def _validate_and_register(self, code: str) -> ForgeResult:
        # Write to temp file, try to import
        try:
            # Compile check
            compile(code, "<forge>", "exec")
        except SyntaxError as e:
            return ForgeResult(success=False, error=f"Syntax error: {e}")

        # Execute in isolated namespace
        namespace: dict = {}
        try:
            exec(code, namespace)
        except Exception as e:
            return ForgeResult(success=False, error=f"Execution error: {e}")

        # Check required attributes
        for attr in REQUIRED_ATTRS:
            if attr not in namespace:
                return ForgeResult(success=False, error=f"Missing required attribute: {attr}")

        skill_id = namespace["SKILL_ID"]
        if not skill_id.startswith("custom."):
            return ForgeResult(success=False, error=f"SKILL_ID must start with 'custom.': {skill_id}")

        # Save to file
        safe_name = skill_id.replace(".", "_") + ".py"
        file_path = self._skills_dir / safe_name
        file_path.write_text(code)

        # Register
        self._registry.register(
            skill_id=skill_id,
            name=namespace["SKILL_NAME"],
            description=namespace["SKILL_DESCRIPTION"],
            handler=namespace["handler"],
            risk_level=namespace.get("SKILL_RISK", "high"),
        )

        logger.info("Forged skill %s -> %s", skill_id, file_path)
        return ForgeResult(success=True, skill_id=skill_id, file_path=str(file_path))
```

**Step 4: Run tests**

Run: `pytest tests/unit/skills/test_forge.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/skills/forge.py tests/unit/skills/test_forge.py
git commit -m "feat: add Skill Forge — generates skills from capability gap descriptions"
```

---

## Task 15: Integrate Forge into Execution Loop

When planning produces tasks with no matching skill, trigger the Forge.

**Files:**
- Modify: `src/atlas/core/loop.py`
- Test: `tests/unit/core/test_forge_integration.py`

**Step 1: Write failing test**

```python
# tests/unit/core/test_forge_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from atlas.core.loop import ExecutionLoop
from atlas.core.tasks import Task
from atlas.core.missions import Mission
from atlas.contracts.types import TaskStatus, MissionStatus, SkillResult

async def test_execution_loop_triggers_forge_on_missing_skill(tmp_path):
    """When a task references a skill that doesn't exist, the loop should attempt forge."""
    registry = MagicMock()
    registry.get.side_effect = Exception("Skill 'custom.deploy' not found")

    forge = AsyncMock()
    forge.create_skill = AsyncMock(return_value=MagicMock(success=False, error="forge disabled in test"))

    loop = ExecutionLoop(
        registry=registry,
        runtime=MagicMock(),
        environment=MagicMock(),
        policy=MagicMock(),
        audit=AsyncMock(),
        approval=AsyncMock(),
        working_memory=MagicMock(),
        episodic_memory=AsyncMock(),
        forge=forge,
    )

    task = Task(description="deploy the app", skill_id="custom.deploy")
    mission = Mission(goal_text="deploy", tasks=[task])
    result = await loop.execute_mission(mission)

    forge.create_skill.assert_called_once()
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/core/test_forge_integration.py -v`
Expected: TypeError — ExecutionLoop doesn't accept `forge` parameter

**Step 3: Implement**

Add optional `forge: SkillForge | None = None` parameter to `ExecutionLoop.__init__()`. In `_execute_task()`, when `registry.get(skill_id)` raises `SkillNotFoundError`, attempt `forge.create_skill()` before failing the task.

**Step 4: Run tests**

Run: `pytest tests/unit/core/test_forge_integration.py tests/unit/core/ tests/integration/ -v`
Expected: All PASS (existing + new)

**Step 5: Commit**

```bash
git add src/atlas/core/loop.py tests/unit/core/test_forge_integration.py
git commit -m "feat: integrate Skill Forge into execution loop for missing skill recovery"
```

---

## Task 16: Pattern Extraction (Background)

Analyze episodic memory to discover repeated patterns and create procedures.

**Files:**
- Create: `src/atlas/memory/patterns.py`
- Test: `tests/unit/memory/test_patterns.py`

**Step 1: Write failing tests**

```python
# tests/unit/memory/test_patterns.py
import pytest
from unittest.mock import AsyncMock
from atlas.memory.patterns import PatternExtractor
from atlas.contracts.types import Episode, EpisodeType

async def test_extracts_repeated_skill_sequence():
    episodes = [
        Episode(episode_type=EpisodeType.TASK_EXECUTION, trigger="run tests",
                actions=[{"skill_id": "shell.execute", "status": "completed"}],
                outcome="completed"),
        Episode(episode_type=EpisodeType.TASK_EXECUTION, trigger="run tests again",
                actions=[{"skill_id": "shell.execute", "status": "completed"}],
                outcome="completed"),
        Episode(episode_type=EpisodeType.TASK_EXECUTION, trigger="run tests once more",
                actions=[{"skill_id": "shell.execute", "status": "completed"}],
                outcome="completed"),
    ]
    extractor = PatternExtractor(min_occurrences=3)
    patterns = extractor.find_patterns(episodes)
    assert len(patterns) >= 1
    assert patterns[0]["skill_sequence"] == ["shell.execute"]

async def test_identifies_recurring_failures():
    episodes = [
        Episode(episode_type=EpisodeType.TASK_EXECUTION, trigger="deploy",
                actions=[{"skill_id": "shell.execute", "status": "failed"}],
                outcome="failed"),
        Episode(episode_type=EpisodeType.TASK_EXECUTION, trigger="deploy again",
                actions=[{"skill_id": "shell.execute", "status": "failed"}],
                outcome="failed"),
    ]
    extractor = PatternExtractor(min_occurrences=2)
    failures = extractor.find_recurring_failures(episodes)
    assert len(failures) >= 1

async def test_no_patterns_below_threshold():
    episodes = [
        Episode(episode_type=EpisodeType.TASK_EXECUTION, trigger="task A",
                actions=[{"skill_id": "file.read", "status": "completed"}],
                outcome="completed"),
    ]
    extractor = PatternExtractor(min_occurrences=3)
    patterns = extractor.find_patterns(episodes)
    assert len(patterns) == 0
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/memory/test_patterns.py -v`
Expected: ImportError

**Step 3: Implement PatternExtractor**

`src/atlas/memory/patterns.py`:

```python
"""Pattern Extraction — discovers repeated patterns in episodic memory."""

from __future__ import annotations

from collections import Counter
from atlas.contracts.types import Episode


class PatternExtractor:
    def __init__(self, min_occurrences: int = 3):
        self._min_occurrences = min_occurrences

    def find_patterns(self, episodes: list[Episode]) -> list[dict]:
        # Extract skill sequences from completed episodes
        sequences: list[tuple[str, ...]] = []
        for ep in episodes:
            if ep.outcome != "completed" or not ep.actions:
                continue
            seq = tuple(
                a.get("skill_id", "") for a in ep.actions
                if a.get("status") == "completed" and a.get("skill_id")
            )
            if seq:
                sequences.append(seq)

        counts = Counter(sequences)
        patterns = []
        for seq, count in counts.most_common():
            if count >= self._min_occurrences:
                patterns.append({
                    "skill_sequence": list(seq),
                    "occurrences": count,
                })
        return patterns

    def find_recurring_failures(self, episodes: list[Episode]) -> list[dict]:
        failure_skills: list[str] = []
        for ep in episodes:
            if ep.outcome != "failed" or not ep.actions:
                continue
            for a in ep.actions:
                if a.get("status") == "failed" and a.get("skill_id"):
                    failure_skills.append(a["skill_id"])

        counts = Counter(failure_skills)
        failures = []
        for skill_id, count in counts.most_common():
            if count >= self._min_occurrences:
                failures.append({"skill_id": skill_id, "failure_count": count})
        # Also return failures with lower threshold (2+) as warnings
        for skill_id, count in counts.most_common():
            if count >= 2 and not any(f["skill_id"] == skill_id for f in failures):
                failures.append({"skill_id": skill_id, "failure_count": count})
        return failures
```

**Step 4: Run tests**

Run: `pytest tests/unit/memory/test_patterns.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/memory/patterns.py tests/unit/memory/test_patterns.py
git commit -m "feat: add pattern extraction for episodic memory analysis"
```

---

## Task 17: Update Configuration

Update default.yaml with Phase 2 settings and wire config loading.

**Files:**
- Modify: `config/default.yaml`
- Create: `src/atlas/config.py`
- Test: `tests/unit/test_config.py`

**Step 1: Write failing tests**

```python
# tests/unit/test_config.py
import pytest
from pathlib import Path
from atlas.config import load_config, AtlasConfig

def test_load_default_config():
    config = load_config()
    assert config.daemon.socket_path.endswith("atlas.sock")
    assert config.daemon.max_concurrent_tasks == 1
    assert config.observation.filesystem_debounce_seconds == 5.0
    assert config.skills.forge_enabled is True
    assert config.reactive.enabled is False

def test_load_config_from_file(tmp_path):
    config_file = tmp_path / "custom.yaml"
    config_file.write_text("""
daemon:
  max_concurrent_tasks: 4
reactive:
  enabled: true
""")
    config = load_config(str(config_file))
    assert config.daemon.max_concurrent_tasks == 4
    assert config.reactive.enabled is True
```

**Step 2: Run to verify failure**

Run: `pytest tests/unit/test_config.py -v`
Expected: ImportError

**Step 3: Implement config loader and update default.yaml**

`src/atlas/config.py` — dataclass-based config with YAML loading, merging user overrides onto defaults.

Update `config/default.yaml` with full Phase 2 settings:

```yaml
atlas:
  data_dir: "~/.atlas"
  log_level: "INFO"

daemon:
  socket_path: "~/.atlas/atlas.sock"
  pid_file: "~/.atlas/daemon.pid"
  max_concurrent_tasks: 1

control:
  autonomy_level: "act_within_bounds"
  allowed_read_paths: ["."]
  allowed_write_paths: ["."]
  blocked_paths: ["~/.ssh", "~/.gnupg"]

memory:
  working_memory_max_keys: 100
  episode_retention_days: 90
  context_default_token_budget: 4000
  pattern_extraction_interval_minutes: 30

skills:
  seed_skills: ["file.read", "file.write", "file.search", "shell.execute"]
  forge_enabled: true
  forge_max_retries: 1
  custom_skills_dir: "~/.atlas/skills"

environment:
  command_timeout_seconds: 30

observation:
  filesystem_debounce_seconds: 5.0
  watches: []

reactive:
  enabled: false
  rules: []
  cooldown_default_seconds: 60
```

**Step 4: Run tests**

Run: `pytest tests/unit/test_config.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/config.py config/default.yaml tests/unit/test_config.py
git commit -m "feat: add structured config loading with Phase 2 defaults"
```

---

## Task 18: Wire Everything into CLI

Connect daemon, observation engine, forge, and config into the CLI entry point.

**Files:**
- Modify: `src/atlas/cli.py`
- Test: manual integration test via `atlas daemon start` and `atlas goal`

**Step 1: Update CLI**

Add `daemon` command group:
- `atlas daemon start` — starts daemon with observation engine, socket server, forge
- `atlas daemon stop` — sends shutdown command via socket
- `atlas daemon status` — queries daemon status via socket

Update `atlas goal`:
- If daemon is running (check PID file), forward goal via socket client
- If no daemon, run inline as before

Add `atlas watch` command group:
- `atlas watch add <pattern>` — adds filesystem watch (persisted to config)
- `atlas watch list` — shows active watches

Load config from `config/default.yaml` with user override from `~/.atlas/config/atlas.yaml`.

Initialize `SkillForge` and `load_skills_from_directory()` on startup.

**Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: All existing + new tests PASS

**Step 3: Commit**

```bash
git add src/atlas/cli.py
git commit -m "feat: wire daemon, forge, observation, and config into CLI"
```

---

## Task 19: End-to-End Integration Test

Full daemon lifecycle test: start daemon, submit goal, verify execution, stop daemon.

**Files:**
- Create: `tests/integration/test_daemon_e2e.py`

**Step 1: Write test**

```python
# tests/integration/test_daemon_e2e.py
import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from atlas.daemon.loop import DaemonLoop
from atlas.daemon.protocol import DaemonSocketClient
from atlas.contracts.types import DaemonCommand

async def test_daemon_full_lifecycle(tmp_path):
    """Start daemon, submit goal, check status, stop daemon."""
    socket_path = str(tmp_path / "test.sock")
    pid_path = str(tmp_path / "test.pid")

    goals_executed = []
    async def mock_executor(goal_text: str) -> dict:
        goals_executed.append(goal_text)
        return {"status": "completed", "tasks": 1}

    daemon = DaemonLoop(
        socket_path=socket_path,
        pid_path=pid_path,
        goal_executor=mock_executor,
    )

    # Start daemon
    task = asyncio.create_task(daemon.start())
    await asyncio.sleep(0.2)

    client = DaemonSocketClient(socket_path)

    # Check status
    status = await client.send(DaemonCommand(command="status"))
    assert status["status"] == "ok"
    assert status["payload"]["running"] is True

    # Submit goal
    result = await client.send(DaemonCommand(
        command="goal", payload={"goal_text": "test goal"},
    ))
    assert result["status"] == "ok"
    assert len(goals_executed) == 1

    # Shutdown
    await client.send(DaemonCommand(command="shutdown"))
    await asyncio.wait_for(task, timeout=2.0)

    # Verify PID file cleaned up
    assert not Path(pid_path).exists()
```

**Step 2: Run test**

Run: `pytest tests/integration/test_daemon_e2e.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/integration/test_daemon_e2e.py
git commit -m "test: add end-to-end daemon lifecycle integration test"
```

---

## Task 20: Final Cleanup and Full Test Run

Run complete test suite, lint, verify everything works together.

**Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 2: Run linter**

Run: `ruff check src/ tests/`
Expected: All checks passed

**Step 3: Commit any fixes**

```bash
git add -A
git commit -m "chore: Phase 2 cleanup — lint fixes, test stabilization"
```

**Step 4: Verify CLI works**

```bash
atlas daemon start &
atlas goal "create a hello world script"
atlas daemon status
atlas daemon stop
```

---

## Build Order Summary

| Task | Component | Depends On |
|------|-----------|------------|
| 1 | Contract types | — |
| 2 | Socket protocol | Task 1 |
| 3 | PID file manager | — |
| 4 | Daemon main loop + CLI | Tasks 2, 3 |
| 5 | Filesystem watcher | Task 1 |
| 6 | Scheduled triggers | Task 1 |
| 7 | Priority task queue | — |
| 8 | Event router | Task 1 |
| 9 | Observation engine + reactive loop | Tasks 5, 6, 8 |
| 10 | Replanning on failure | — |
| 11 | Procedural memory | Task 1 |
| 12 | Purpose-aware context assembly | Task 11 |
| 13 | Skill loader | — |
| 14 | Skill Forge | Task 13 |
| 15 | Forge in execution loop | Tasks 10, 14 |
| 16 | Pattern extraction | Task 11 |
| 17 | Configuration | — |
| 18 | Wire into CLI | Tasks 4, 9, 14, 17 |
| 19 | E2E integration test | Task 18 |
| 20 | Final cleanup | Task 19 |

**Parallelizable groups:**
- Tasks 1-3 can run in parallel (no deps)
- Tasks 5-8 can run in parallel after Task 1
- Tasks 10-13 can run in parallel
