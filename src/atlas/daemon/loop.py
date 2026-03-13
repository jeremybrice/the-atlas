"""Daemon main loop -- runs the socket server and dispatches commands."""
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
                asyncio.get_event_loop().call_soon(lambda: asyncio.ensure_future(self.stop()))
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
