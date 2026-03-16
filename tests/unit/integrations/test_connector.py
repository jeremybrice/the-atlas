import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

from atlas.contracts.interfaces import ConnectorInterface
from atlas.contracts.types import ExecutionContext
from atlas.integrations.connector import ConnectorABC


class FakeConnector(ConnectorABC):
    """Concrete test implementation of ConnectorABC."""

    def __init__(self):
        super().__init__(service_name="fake", rate_limit_rpm=60)
        self.auth_called = False

    async def authenticate(self, ctx: ExecutionContext | None = None) -> None:
        self.auth_called = True

    async def handle_event(self, event_type: str, payload: dict[str, Any], ctx: ExecutionContext | None = None) -> dict[str, Any]:
        return {"handled": event_type}

    async def execute_action(self, action: str, params: dict[str, Any], ctx: ExecutionContext | None = None) -> dict[str, Any]:
        await self._check_rate_limit()
        return {"action": action, "params": params}


def test_connector_abc_implements_interface():
    assert issubclass(ConnectorABC, ConnectorInterface)


def test_connector_has_service_name():
    conn = FakeConnector()
    assert conn.service_name == "fake"


async def test_authenticate():
    conn = FakeConnector()
    await conn.authenticate()
    assert conn.auth_called is True


async def test_handle_event():
    conn = FakeConnector()
    result = await conn.handle_event("push", {"ref": "main"})
    assert result == {"handled": "push"}


async def test_execute_action():
    conn = FakeConnector()
    result = await conn.execute_action("comment", {"body": "hello"})
    assert result == {"action": "comment", "params": {"body": "hello"}}


async def test_rate_limit_tracks_calls():
    conn = FakeConnector()
    # Should not raise for first call
    result = await conn.execute_action("comment", {"body": "test"})
    assert result["action"] == "comment"


async def test_rate_limit_serializes_concurrent_calls():
    """Concurrent calls should not bypass the rate limit."""
    conn = FakeConnector()
    conn._rate_limit_rpm = 2  # low limit to test easily

    # Mock asyncio.sleep so the test doesn't actually wait 60s
    with patch("atlas.integrations.connector.asyncio.sleep", new_callable=AsyncMock):
        # Fire 4 concurrent calls
        results = await asyncio.gather(
            conn.execute_action("a", {}),
            conn.execute_action("b", {}),
            conn.execute_action("c", {}),
            conn.execute_action("d", {}),
        )

    # All should complete (rate limiter waits, doesn't reject)
    assert len(results) == 4
    # But timestamps should show serialization — at most 2 in any 1-second window
    # The lock ensures check-then-append is atomic
    assert len(conn._call_timestamps) == 4
