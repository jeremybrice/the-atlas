"""Claude Code Bridge — calls the Anthropic Messages API via the Python SDK.

Authentication
--------------
The bridge authenticates using an API key, resolved in this order:

1. ``api_key`` parameter passed to ``ClaudeCodeBridge.__init__``
2. ``ANTHROPIC_API_KEY`` environment variable (read automatically by the SDK)

If neither is available, the bridge raises ``ClaudeCodeUnavailableError``
at construction time rather than failing on the first API call.
"""

from __future__ import annotations

import json
import logging
import os
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
    """Calls the Anthropic Messages API via async client.

    Parameters
    ----------
    model : str
        Model identifier (default: ``claude-sonnet-4-20250514``).
    timeout : int
        Request timeout in seconds (default: 120).
    api_key : str | None
        Explicit API key. When *None*, falls back to ``ANTHROPIC_API_KEY``
        environment variable.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        timeout: int = 120,
        api_key: str | None = None,
    ):
        self._model = model
        self._timeout = timeout

        # Resolve the API key: explicit arg → env var → fail fast
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ClaudeCodeUnavailableError(
                "No Anthropic API key found. Set the ANTHROPIC_API_KEY environment "
                "variable or pass api_key= to ClaudeCodeBridge."
            )

        self._client = anthropic.AsyncAnthropic(
            api_key=resolved_key, timeout=timeout
        )

    async def oneshot(
        self, prompt: str, system_prompt: str | None = None
    ) -> ClaudeResponse:
        """Send a one-shot prompt to the Anthropic Messages API.

        Raises
        ------
        ClaudeCodeUnavailableError
            If the API key is invalid (HTTP 401).
        ClaudeCodeError
            On transient failures (timeouts, rate limits, server errors).
        """
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
                "Anthropic API key is invalid or expired. Check your "
                "ANTHROPIC_API_KEY environment variable."
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
                message.model,
                message.stop_reason,
                elapsed,
            )

        response = parse_response_text(text)
        response.execution_time_ms = elapsed
        response.tokens_used = message.usage.input_tokens + message.usage.output_tokens
        return response
