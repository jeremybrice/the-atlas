# tests/unit/env/test_claude.py

import os

import pytest

from atlas.contracts.errors import ClaudeCodeUnavailableError
from atlas.env.claude import ClaudeCodeBridge, parse_response_text


def test_parse_plain_text():
    text = "Here is the plan:\n1. Read file\n2. Modify it\n3. Write it back"
    response = parse_response_text(text)
    assert response.content == text
    assert response.parsed_output is None


def test_parse_json_block():
    text = """Here is the plan:
```json
{"tasks": [{"description": "read file", "skill": "file.read"}]}
```
Done."""
    response = parse_response_text(text)
    assert response.parsed_output is not None
    assert response.parsed_output["tasks"][0]["skill"] == "file.read"


def test_parse_no_json():
    text = "Just a text response with no structured data."
    response = parse_response_text(text)
    assert response.content == text
    assert response.parsed_output is None


def test_parse_invalid_json_block():
    text = "```json\n{invalid json}\n```"
    response = parse_response_text(text)
    assert response.parsed_output is None
    assert response.content == text


def test_parse_raw_json():
    text = '{"tasks": [{"description": "test", "skill": "file.read"}]}'
    response = parse_response_text(text)
    assert response.parsed_output is not None
    assert response.parsed_output["tasks"][0]["description"] == "test"


def test_bridge_uses_async_client():
    """ClaudeCodeBridge should use AsyncAnthropic, not sync Anthropic."""
    import anthropic as _anthropic

    bridge = ClaudeCodeBridge(api_key="test-key")
    assert isinstance(bridge._client, _anthropic.AsyncAnthropic)


def test_bridge_accepts_explicit_api_key():
    """ClaudeCodeBridge should accept an explicit api_key parameter."""
    bridge = ClaudeCodeBridge(api_key="sk-ant-test-key")
    assert bridge._client.api_key == "sk-ant-test-key"


def test_bridge_reads_api_key_from_env(monkeypatch):
    """ClaudeCodeBridge should fall back to ANTHROPIC_API_KEY env var."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-key")
    bridge = ClaudeCodeBridge()
    assert bridge._client.api_key == "sk-ant-env-key"


def test_bridge_raises_without_api_key(monkeypatch):
    """ClaudeCodeBridge should raise immediately if no API key is available."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ClaudeCodeUnavailableError, match="No Anthropic API key found"):
        ClaudeCodeBridge()


def test_bridge_explicit_key_overrides_env(monkeypatch):
    """Explicit api_key should take precedence over env var."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-key")
    bridge = ClaudeCodeBridge(api_key="sk-ant-explicit-key")
    assert bridge._client.api_key == "sk-ant-explicit-key"


def test_bridge_custom_model_and_timeout():
    """ClaudeCodeBridge should accept custom model and timeout."""
    bridge = ClaudeCodeBridge(
        model="claude-opus-4-20250514",
        timeout=60,
        api_key="test-key",
    )
    assert bridge._model == "claude-opus-4-20250514"
    assert bridge._timeout == 60
