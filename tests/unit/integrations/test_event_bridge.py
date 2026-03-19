import hashlib
import hmac
from atlas.integrations.event_bridge import EventBridge
from atlas.contracts.types import EventType, ObservationEvent


def test_register_parser():
    bridge = EventBridge()
    bridge.register_parser(
        "github",
        lambda et, p: ObservationEvent(
            event_type=EventType.WEBHOOK,
            source="github",
            payload=p,
        ),
    )
    assert "github" in bridge.parsers


def test_parse_event():
    bridge = EventBridge()
    bridge.register_parser(
        "github",
        lambda et, p: ObservationEvent(
            event_type=EventType.WEBHOOK,
            source="github",
            payload=p,
        ),
    )
    event = bridge.parse("github", "push", {"ref": "refs/heads/main"})
    assert event is not None
    assert event.event_type == EventType.WEBHOOK
    assert event.source == "github"
    assert event.payload == {"ref": "refs/heads/main"}


def test_parse_unknown_service_returns_none():
    bridge = EventBridge()
    event = bridge.parse("unknown_service", "push", {})
    assert event is None


def test_verify_github_signature():
    bridge = EventBridge()
    secret = "test-secret"
    body = b'{"action":"opened"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert bridge.verify_signature("github", body, sig, secret) is True


def test_verify_github_signature_invalid():
    bridge = EventBridge()
    assert (
        bridge.verify_signature("github", b"body", "sha256=invalid", "secret") is False
    )


def test_verify_unknown_service_returns_false():
    bridge = EventBridge()
    assert bridge.verify_signature("unknown", b"body", "sig", "secret") is False


def test_parsed_event_has_correlation_id():
    bridge = EventBridge()
    bridge.register_parser(
        "github",
        lambda et, p: ObservationEvent(
            event_type=EventType.WEBHOOK,
            source="github",
            payload=p,
        ),
    )
    event = bridge.parse("github", "push", {"ref": "main"})
    assert event is not None
    assert event.correlation_id
    assert isinstance(event.correlation_id, str)
