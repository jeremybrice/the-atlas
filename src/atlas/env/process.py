"""Process Provider — spawn and manage external processes."""

from __future__ import annotations

import asyncio
import time


class ProcessProvider:
    """Async process execution with timeout support."""

    def __init__(self, default_timeout: int = 30):
        self._default_timeout = default_timeout

    async def execute(
        self, cmd: str, cwd: str | None = None, timeout: int | None = None
    ) -> dict:
        timeout = timeout or self._default_timeout
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            elapsed = int((time.monotonic() - start) * 1000)

            return {
                "exit_code": proc.returncode,
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
                "execution_time_ms": elapsed,
            }
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            elapsed = int((time.monotonic() - start) * 1000)
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": "",
                "error": f"Timeout after {timeout}s",
                "execution_time_ms": elapsed,
            }
