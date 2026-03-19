# tests/unit/env/test_claude.py

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

    bridge = ClaudeCodeBridge.__new__(ClaudeCodeBridge)
    bridge._model = "test"
    bridge._timeout = 60
    bridge._client = _anthropic.AsyncAnthropic(api_key="test-key")
    assert isinstance(bridge._client, _anthropic.AsyncAnthropic)
