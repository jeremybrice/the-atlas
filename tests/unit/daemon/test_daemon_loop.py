import asyncio
import tempfile
from unittest.mock import AsyncMock, MagicMock
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
        resp = await client.send(
            DaemonCommand(command="goal", payload={"goal_text": "test goal"})
        )
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

    loop = DaemonLoop(
        socket_path=socket_path, pid_path=pid_path, goal_executor=executor
    )
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

    loop = DaemonLoop(
        socket_path=socket_path, pid_path=pid_path, goal_executor=executor
    )
    task = asyncio.create_task(loop.start())
    await asyncio.sleep(0.1)

    from atlas.daemon.protocol import DaemonSocketClient

    client = DaemonSocketClient(socket_path)
    resp = await client.send(DaemonCommand(command="shutdown"))
    assert resp["status"] == "ok"

    await task  # should exit cleanly


async def test_daemon_loop_status_includes_http_running():
    tmpdir = tempfile.mkdtemp()
    socket_path = f"{tmpdir}/t.sock"
    pid_path = f"{tmpdir}/t.pid"
    executor = AsyncMock()

    loop = DaemonLoop(
        socket_path=socket_path, pid_path=pid_path, goal_executor=executor
    )
    task = asyncio.create_task(loop.start())
    await asyncio.sleep(0.1)

    try:
        from atlas.daemon.protocol import DaemonSocketClient

        client = DaemonSocketClient(socket_path)
        resp = await client.send(DaemonCommand(command="status"))
        assert resp["status"] == "ok"
        assert "http_running" in resp["payload"]
        assert resp["payload"]["http_running"] is False  # no http_app configured
    finally:
        await loop.stop()
        await task


async def test_daemon_loop_accepts_mcp_bridge():
    """DaemonLoop should accept an optional MCPBridge and MCP servers config."""
    mock_bridge = MagicMock()
    mock_bridge.register_tools = MagicMock(return_value=[])
    mock_bridge.unregister_server = MagicMock()
    mock_bridge.list_servers = MagicMock(return_value={})

    loop = DaemonLoop(
        socket_path="/tmp/test.sock",
        pid_path="/tmp/test.pid",
        mcp_bridge=mock_bridge,
        mcp_servers=[],
    )
    assert loop._mcp_bridge is mock_bridge
    assert loop._mcp_servers == []


async def test_daemon_loop_pause_command():
    tmpdir = tempfile.mkdtemp()
    socket_path = f"{tmpdir}/t.sock"
    pid_path = f"{tmpdir}/t.pid"
    executor = AsyncMock()

    loop = DaemonLoop(
        socket_path=socket_path, pid_path=pid_path, goal_executor=executor
    )
    task = asyncio.create_task(loop.start())
    await asyncio.sleep(0.1)

    try:
        from atlas.daemon.protocol import DaemonSocketClient

        client = DaemonSocketClient(socket_path)
        resp = await client.send(DaemonCommand(command="pause"))
        assert resp["status"] == "ok"

        # Status should now report paused
        status_resp = await client.send(DaemonCommand(command="status"))
        assert status_resp["payload"]["paused"] is True
    finally:
        await loop.stop()
        await task


async def test_daemon_loop_resume_command():
    tmpdir = tempfile.mkdtemp()
    socket_path = f"{tmpdir}/t.sock"
    pid_path = f"{tmpdir}/t.pid"
    executor = AsyncMock()

    loop = DaemonLoop(
        socket_path=socket_path, pid_path=pid_path, goal_executor=executor
    )
    task = asyncio.create_task(loop.start())
    await asyncio.sleep(0.1)

    try:
        from atlas.daemon.protocol import DaemonSocketClient

        client = DaemonSocketClient(socket_path)
        await client.send(DaemonCommand(command="pause"))
        resp = await client.send(DaemonCommand(command="resume"))
        assert resp["status"] == "ok"

        status_resp = await client.send(DaemonCommand(command="status"))
        assert status_resp["payload"]["paused"] is False
    finally:
        await loop.stop()
        await task


async def test_daemon_loop_kill_command_no_active_task():
    tmpdir = tempfile.mkdtemp()
    socket_path = f"{tmpdir}/t.sock"
    pid_path = f"{tmpdir}/t.pid"
    executor = AsyncMock()

    loop = DaemonLoop(
        socket_path=socket_path, pid_path=pid_path, goal_executor=executor
    )
    task = asyncio.create_task(loop.start())
    await asyncio.sleep(0.1)

    try:
        from atlas.daemon.protocol import DaemonSocketClient

        client = DaemonSocketClient(socket_path)
        resp = await client.send(
            DaemonCommand(command="kill", payload={"task_id": "nonexistent"})
        )
        assert resp["status"] == "ok"
        assert resp["payload"]["killed"] is False
    finally:
        await loop.stop()
        await task
