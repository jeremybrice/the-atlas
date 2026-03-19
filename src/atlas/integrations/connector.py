"""Connector ABC — base class for external service integrations."""

import asyncio
import logging
import time
from abc import abstractmethod
from typing import Any

from atlas.contracts.interfaces import ConnectorInterface
from atlas.contracts.types import ExecutionContext

logger = logging.getLogger(__name__)


class ConnectorABC(ConnectorInterface):
    """Base class for all external service connectors.

    Provides rate limiting and a standard interface for authentication,
    event handling, and action execution.
    """

    def __init__(self, service_name: str, rate_limit_rpm: int = 60):
        self._service_name = service_name
        self._rate_limit_rpm = rate_limit_rpm
        self._call_timestamps: list[float] = []
        self._rate_limit_lock = asyncio.Lock()

    @property
    def service_name(self) -> str:
        return self._service_name

    @abstractmethod
    async def authenticate(self, ctx: ExecutionContext | None = None) -> None:
        """Authenticate with the external service."""
        ...

    @abstractmethod
    async def handle_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        ctx: ExecutionContext | None = None,
    ) -> dict[str, Any]:
        """Handle an incoming event from the external service."""
        ...

    @abstractmethod
    async def execute_action(
        self, action: str, params: dict[str, Any], ctx: ExecutionContext | None = None
    ) -> dict[str, Any]:
        """Execute an outbound action on the external service."""
        ...

    async def _check_rate_limit(self) -> None:
        """Wait if rate limit would be exceeded."""
        async with self._rate_limit_lock:
            now = time.monotonic()
            window = 60.0  # 1 minute window
            # Prune old timestamps
            self._call_timestamps = [
                t for t in self._call_timestamps if now - t < window
            ]
            if len(self._call_timestamps) >= self._rate_limit_rpm:
                wait_time = window - (now - self._call_timestamps[0])
                if wait_time > 0:
                    logger.warning(
                        "%s rate limit reached (%d rpm), waiting %.1fs",
                        self._service_name,
                        self._rate_limit_rpm,
                        wait_time,
                    )
                    await asyncio.sleep(wait_time)
            self._call_timestamps.append(time.monotonic())
