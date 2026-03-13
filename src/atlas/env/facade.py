"""Environment Facade — single entry point for all environment interactions."""

from __future__ import annotations

from atlas.contracts.types import (
    ActionResult,
    ClaudeResponse,
    EnvironmentAction,
    ExecutionContext,
)
from atlas.env.claude import ClaudeCodeBridge
from atlas.env.filesystem import FilesystemProvider
from atlas.env.process import ProcessProvider
from atlas.env.state import EnvironmentStateModel


class EnvironmentFacade:
    """Routes EnvironmentAction objects to the appropriate provider."""

    def __init__(
        self,
        filesystem: FilesystemProvider | None = None,
        process: ProcessProvider | None = None,
        claude: ClaudeCodeBridge | None = None,
    ):
        self._fs = filesystem or FilesystemProvider()
        self._proc = process or ProcessProvider()
        self._claude = claude or ClaudeCodeBridge()
        self._state = EnvironmentStateModel(self._fs)

    async def execute(
        self, action: EnvironmentAction, ctx: ExecutionContext | None = None
    ) -> ActionResult:
        try:
            match action.action_type:
                case "filesystem_read":
                    content = self._fs.read(action.params["path"])
                    return ActionResult(
                        action_id=action.action_id, status="success", output=content
                    )
                case "filesystem_write":
                    self._fs.write(action.params["path"], action.params["content"])
                    return ActionResult(
                        action_id=action.action_id, status="success"
                    )
                case "filesystem_search":
                    results = self._fs.search(
                        action.params.get("root", "."),
                        action.params["pattern"],
                    )
                    return ActionResult(
                        action_id=action.action_id, status="success", output=results
                    )
                case "process_execute":
                    result = await self._proc.execute(
                        action.params["command"],
                        cwd=action.params.get("cwd"),
                        timeout=action.timeout,
                    )
                    status = "success" if result["exit_code"] == 0 else "failure"
                    return ActionResult(
                        action_id=action.action_id,
                        status=status,
                        output=result,
                        error=result.get("error"),
                    )
                case _:
                    return ActionResult(
                        action_id=action.action_id,
                        status="failure",
                        error=f"Unknown action type: {action.action_type}",
                    )
        except Exception as e:
            return ActionResult(
                action_id=action.action_id,
                status="failure",
                error=str(e),
            )

    def get_state(self) -> dict:
        return self._state.snapshot()

    async def claude_oneshot(
        self,
        prompt: str,
        system_prompt: str | None = None,
        ctx: ExecutionContext | None = None,
    ) -> ClaudeResponse:
        return await self._claude.oneshot(prompt, system_prompt)
