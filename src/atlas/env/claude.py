"""Claude Code Bridge — manages interactions with the Claude Code CLI."""

from __future__ import annotations

import asyncio
import json
import re
import time

from atlas.contracts.errors import ClaudeCodeError, ClaudeCodeUnavailableError
from atlas.contracts.types import ClaudeResponse


def parse_claude_response(raw: str) -> ClaudeResponse:
    """Extract structured output from Claude Code CLI response text."""
    parsed = None
    # Look for ```json ... ``` blocks
    pattern = r"```json\s*\n(.*?)\n```"
    match = re.search(pattern, raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            parsed = None

    return ClaudeResponse(content=raw, parsed_output=parsed)


class ClaudeCodeBridge:
    """Manages Claude Code CLI subprocess calls. Phase 1: one-shot only."""

    def __init__(self, timeout: int = 120):
        self._timeout = timeout

    async def oneshot(
        self, prompt: str, system_prompt: str | None = None
    ) -> ClaudeResponse:
        cmd = ["claude", "-p", prompt]
        if system_prompt:
            cmd.extend(["--system", system_prompt])

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
        except FileNotFoundError:
            raise ClaudeCodeUnavailableError(
                "Claude Code CLI not found. Is 'claude' on PATH?"
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise ClaudeCodeError(
                f"Claude Code CLI timed out after {self._timeout}s"
            )

        elapsed = int((time.monotonic() - start) * 1000)

        if proc.returncode != 0:
            error_text = stderr.decode(errors="replace").strip()
            raise ClaudeCodeError(
                f"Claude Code CLI exited with code {proc.returncode}: {error_text}"
            )

        raw_output = stdout.decode(errors="replace")
        response = parse_claude_response(raw_output)
        response.execution_time_ms = elapsed
        return response
