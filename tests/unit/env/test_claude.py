# tests/unit/env/test_claude.py


from atlas.env.claude import parse_claude_response


def test_parse_claude_response_plain_text():
    raw = "Here is the plan:\n1. Read file\n2. Modify it\n3. Write it back"
    response = parse_claude_response(raw)
    assert response.content == raw
    assert response.parsed_output is None


def test_parse_claude_response_json_block():
    raw = '''Here is the plan:
```json
{"tasks": [{"description": "read file", "skill": "file.read"}]}
```
Done.'''
    response = parse_claude_response(raw)
    assert response.parsed_output is not None
    assert response.parsed_output["tasks"][0]["skill"] == "file.read"


def test_parse_claude_response_no_json():
    raw = "Just a text response with no structured data."
    response = parse_claude_response(raw)
    assert response.content == raw
    assert response.parsed_output is None


def test_parse_claude_response_invalid_json_block():
    raw = '```json\n{invalid json}\n```'
    response = parse_claude_response(raw)
    assert response.parsed_output is None
    assert response.content == raw
