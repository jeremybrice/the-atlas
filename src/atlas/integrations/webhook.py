"""Webhook Server — HTTP endpoint for receiving webhook payloads from external services."""
import logging
from typing import Any, Callable, Coroutine

from aiohttp import web

from atlas.contracts.types import ObservationEvent
from atlas.integrations.event_bridge import EventBridge

logger = logging.getLogger(__name__)

EventCallback = Callable[[ObservationEvent], Coroutine[Any, Any, None]]


class WebhookServer:
    """Lightweight aiohttp server for webhook ingestion."""

    def __init__(
        self,
        event_bridge: EventBridge,
        event_callback: EventCallback,
        webhook_path_prefix: str = "/webhooks",
    ):
        self._bridge = event_bridge
        self._callback = event_callback
        self._prefix = webhook_path_prefix
        self._app: web.Application | None = None

    def create_app(self) -> web.Application:
        app = web.Application()
        app.router.add_post(f"{self._prefix}/{{service}}", self._handle_webhook)
        app.router.add_get("/health", self._handle_health)
        self._app = app
        return app

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        service = request.match_info["service"]
        try:
            payload = await request.json()
        except Exception:
            return web.json_response(
                {"status": "error", "message": "invalid JSON"}, status=400,
            )

        # Extract event type from headers (service-specific)
        event_type = self._extract_event_type(service, request)

        event = self._bridge.parse(service, event_type, payload)
        if event is None:
            return web.json_response(
                {"status": "error", "message": f"no parser for service: {service}"},
                status=400,
            )

        # Fire-and-forget to the callback
        try:
            await self._callback(event)
        except Exception as e:
            logger.error("Event callback failed for %s: %s", service, e)

        return web.json_response({"status": "accepted", "event_id": event.event_id})

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    def _extract_event_type(self, service: str, request: web.Request) -> str:
        if service == "github":
            return request.headers.get("X-GitHub-Event", "unknown")
        if service == "slack":
            return request.headers.get("X-Slack-Event", "unknown")
        return "unknown"
