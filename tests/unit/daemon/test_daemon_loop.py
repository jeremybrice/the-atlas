import asyncio
import tempfile
from unittest.mock import AsyncMock
from atlas.daemon.loop import DaemonLoop
from atlas.contracts.types import DaemonCommand


async def test_daemon_loop_handles_goal_command():
    tmpdir = tempfile.mkdtemp()
    socket_path = f"{tmpdir}/t.sock"
    pid_path = f"{tmpdir}/t.pid"

    executor = AsyncMock(return_value={"status": "completed", "tasks": 3})

    loop = DaemonLoop(
        socket_path=socket_path,
        pid_path=pid_path,
        goal_executor=executor,
    )

    task = asyncio.create_task(loop.start())
    await asyncio.sleep(0.1)

    try:
        from atlas.daemon.protocol import DaemonSocketClient
        client = DaemonSocketClient(socket_path)
        resp = await client.send(DaemonCommand(command="goal", payload={"goal_text": "test goal"}))
        assert resp["status"] == "ok"
        executor.assert_called_once()
    finally:
        await loop.stop()
        await task


async def test_daemon_loop_status_command():
    tmpdir = tempfile.mkdtemp()
    socket_path = f"{tmpdir}/t.sock"
    pid_path = f"{tmpdir}/t.pid"
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


async def test_daemon_loop_shutdown_command():
    tmpdir = tempfile.mkdtemp()
    socket_path = f"{tmpdir}/t.sock"
    pid_path = f"{tmpdir}/t.pid"
    executor = AsyncMock()

    loop = DaemonLoop(socket_path=socket_path, pid_path=pid_path, goal_executor=executor)
    task = asyncio.create_task(loop.start())
    await asyncio.sleep(0.1)

    from atlas.daemon.protocol import DaemonSocketClient
    client = DaemonSocketClient(socket_path)
    resp = await client.send(DaemonCommand(command="shutdown"))
    assert resp["status"] == "ok"

    await task  # should exit cleanly
