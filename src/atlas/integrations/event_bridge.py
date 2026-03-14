"""Event Bridge — normalizes external webhook payloads into ObservationEvents."""
import hashlib
import hmac
import logging
from typing import Any, Callable

from atlas.contracts.types import ObservationEvent

logger = logging.getLogger(__name__)

# Parser signature: (event_type: str, payload: dict) -> ObservationEvent
EventParser = Callable[[str, dict[str, Any]], ObservationEvent]


class EventBridge:
    """Normalizes raw webhook payloads from different services into ObservationEvents."""

    def __init__(self):
        self._parsers: dict[str, EventParser] = {}

    @property
    def parsers(self) -> dict[str, EventParser]:
        return dict(self._parsers)

    def register_parser(self, service: str, parser: EventParser) -> None:
        self._parsers[service] = parser
        logger.info("Registered event parser for %s", service)

    def parse(self, service: str, event_type: str, payload: dict) -> ObservationEvent | None:
        parser = self._parsers.get(service)
        if parser is None:
            logger.warning("No parser registered for service: %s", service)
            return None
        try:
            return parser(event_type, payload)
        except Exception as e:
            logger.error("Failed to parse event from %s: %s", service, e)
            return None

    def verify_signature(
        self, service: str, body: bytes, signature: str, secret: str
    ) -> bool:
        """Verify webhook signature. Currently supports GitHub HMAC-SHA256."""
        if service == "github":
            return self._verify_github(body, signature, secret)
        # Default: no verification available
        logger.warning("No signature verification for service: %s", service)
        return True

    def _verify_github(self, body: bytes, signature: str, secret: str) -> bool:
        if not signature.startswith("sha256="):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature[7:], expected)
