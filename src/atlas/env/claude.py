"""Claude Code Bridge — calls the Anthropic API via the Python SDK."""

from __future__ import annotations

import json
import logging
import re
import time

import anthropic

from atlas.contracts.errors import ClaudeCodeError, ClaudeCodeUnavailableError
from atlas.contracts.types import ClaudeResponse

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-20250514"


def parse_response_text(text: str) -> ClaudeResponse:
    """Parse the text content from a Claude API response.

    Tries to extract structured JSON from the text.
    """
    parsed = None

    # 1. ```json ... ``` blocks
    match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 2. Raw JSON (entire content)
    if parsed is None:
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

    return ClaudeResponse(content=text, parsed_output=parsed)


class ClaudeCodeBridge:
    """Calls the Anthropic Messages API via async client."""

    def __init__(self, model: str = DEFAULT_MODEL, timeout: int = 120):
        self._model = model
        self._timeout = timeout
        self._client = anthropic.AsyncAnthropic(timeout=timeout)

    async def oneshot(
        self, prompt: str, system_prompt: str | None = None
    ) -> ClaudeResponse:
        start = time.monotonic()
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=2048,
                system=system_prompt or "",
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AuthenticationError as e:
            raise ClaudeCodeUnavailableError(
                "ANTHROPIC_API_KEY not set or invalid."
            ) from e
        except anthropic.APITimeoutError as e:
            raise ClaudeCodeError(
                f"Anthropic API timed out after {self._timeout}s"
            ) from e
        except anthropic.APIError as e:
            raise ClaudeCodeError(f"Anthropic API error: {e}") from e

        elapsed = int((time.monotonic() - start) * 1000)

        # Extract text from the response
        text = ""
        for block in message.content:
            if block.type == "text":
                text += block.text

        if not text.strip():
            logger.warning(
                "Claude returned empty text. model=%s, stop_reason=%s, elapsed=%dms",
                message.model, message.stop_reason, elapsed,
            )

        response = parse_response_text(text)
        response.execution_time_ms = elapsed
        response.tokens_used = message.usage.input_tokens + message.usage.output_tokens
        return response
