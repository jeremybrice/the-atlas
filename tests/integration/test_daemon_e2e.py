# tests/integration/test_daemon_e2e.py
import asyncio
import tempfile
from pathlib import Path

from atlas.daemon.loop import DaemonLoop
from atlas.daemon.protocol import DaemonSocketClient
from atlas.contracts.types import DaemonCommand


async def test_daemon_full_lifecycle():
    """Start daemon, submit goal, check status, stop daemon."""
    tmpdir = tempfile.mkdtemp()
    socket_path = f"{tmpdir}/t.sock"
    pid_path = f"{tmpdir}/t.pid"

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
    result = await client.send(
        DaemonCommand(
            command="goal",
            payload={"goal_text": "test goal"},
        )
    )
    assert result["status"] == "ok"
    assert len(goals_executed) == 1

    # Shutdown
    await client.send(DaemonCommand(command="shutdown"))
    await asyncio.wait_for(task, timeout=2.0)

    # Verify PID file cleaned up
    assert not Path(pid_path).exists()
