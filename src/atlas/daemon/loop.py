"""Daemon main loop -- runs the socket server and dispatches commands."""
import asyncio
import logging
import os
import time
from typing import Any, Callable, Coroutine

from atlas.control.emergency import EmergencyController
from atlas.daemon.manager import PidFile
from atlas.daemon.protocol import DaemonSocketServer

logger = logging.getLogger(__name__)


class DaemonLoop:
    def __init__(
        self,
        socket_path: str,
        pid_path: str,
        goal_executor: Callable[..., Coroutine[Any, Any, dict]] | None = None,
        mcp_bridge: Any | None = None,
        mcp_servers: list[dict] | None = None,
        http_app: Any | None = None,
        http_host: str = "127.0.0.1",
        http_port: int = 8484,
        emergency_controller: EmergencyController | None = None,
    ):
        self._socket_path = socket_path
        self._pid_file = PidFile(pid_path)
        self._goal_executor = goal_executor
        self._mcp_bridge = mcp_bridge
        self._mcp_servers = mcp_servers or []
        self._server: DaemonSocketServer | None = None
        self._running = False
        self._start_time = 0.0
        self._http_app = http_app
        self._http_host = http_host
        self._http_port = http_port
        self._http_runner = None
        self._http_running = False
        self._emergency = emergency_controller or EmergencyController()

    async def start(self) -> None:
        self._start_time = time.monotonic()
        self._running = True
        self._pid_file.write(os.getpid())

        # Connect MCP servers if configured
        await self._connect_mcp_servers()

        self._server = DaemonSocketServer(self._socket_path, self._handle_command)
        await self._server.start()
        logger.info("Daemon started. PID=%d socket=%s", os.getpid(), self._socket_path)

        # Start HTTP server if configured
        if self._http_app:
            from aiohttp import web
            self._http_runner = web.AppRunner(self._http_app)
            await self._http_runner.setup()
            site = web.TCPSite(self._http_runner, self._http_host, self._http_port)
            try:
                await site.start()
            except OSError as e:
                await self._http_runner.cleanup()
                self._http_runner = None
                logger.error(
                    "Failed to start HTTP server on %s:%d — %s. "
                    "Daemon continues without HTTP.",
                    self._http_host, self._http_port, e,
                )
            else:
                logger.info("HTTP server started on %s:%d", self._http_host, self._http_port)
                self._http_running = True

        while self._running:
            await asyncio.sleep(0.1)

        # Disconnect MCP servers on shutdown
        self._disconnect_mcp_servers()
        if self._http_runner:
            await self._http_runner.cleanup()
            self._http_running = False
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
            case "pause":
                self._emergency.pause()
                return {"command_id": command_id, "status": "ok", "payload": {"message": "paused"}}
            case "resume":
                self._emergency.resume()
                return {"command_id": command_id, "status": "ok", "payload": {"message": "resumed"}}
            case "kill":
                task_id = data.get("payload", {}).get("task_id", "")
                killed = self._emergency.kill_task(task_id)
                return {"command_id": command_id, "status": "ok", "payload": {"killed": killed}}
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

    @property
    def emergency(self) -> EmergencyController:
        return self._emergency

    def _handle_status(self, command_id: str) -> dict:
        uptime = time.monotonic() - self._start_time
        return {
            "command_id": command_id,
            "status": "ok",
            "payload": {
                "pid": os.getpid(),
                "uptime_seconds": round(uptime, 1),
                "running": self._running,
                "http_running": self._http_running,
                "paused": self._emergency.is_paused,
                "active_task_id": self._emergency.active_task_id,
            },
        }

    async def _connect_mcp_servers(self) -> None:
        """Connect to configured MCP servers and register their tools."""
        if not self._mcp_bridge or not self._mcp_servers:
            return
        for server_cfg in self._mcp_servers:
            server_name = server_cfg.get("name", "")
            if not server_name:
                continue
            logger.info("MCP server configured: %s (connection deferred to first use)", server_name)

    def _disconnect_mcp_servers(self) -> None:
        """Unregister all MCP server tools on shutdown."""
        if not self._mcp_bridge:
            return
        for server_name in list(self._mcp_bridge.list_servers().keys()):
            self._mcp_bridge.unregister_server(server_name)
            logger.info("Disconnected MCP server: %s", server_name)
