import pytest
from unittest.mock import AsyncMock, MagicMock
from atlas.integrations.mcp import MCPBridge, MCPSkillAdapter
from atlas.skills.registry import SkillRegistry
from atlas.contracts.types import RiskLevel
from atlas.contracts.errors import ConnectorError


@pytest.fixture
def registry():
    return SkillRegistry()


def test_mcp_skill_adapter_creates_handler():
    mock_session = MagicMock()
    adapter = MCPSkillAdapter(
        session=mock_session,
        tool_name="test_tool",
        tool_description="A test tool",
        input_schema={"type": "object", "properties": {"arg1": {"type": "string"}}},
    )
    assert adapter.skill_id == "mcp.test_tool"
    assert adapter.name == "test_tool"
    assert adapter.description == "A test tool"
    assert adapter.risk_level == RiskLevel.HIGH
    assert callable(adapter.handler)


async def test_mcp_skill_adapter_handler_calls_session():
    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(
        content=[MagicMock(text="result text")]
    ))

    adapter = MCPSkillAdapter(
        session=mock_session,
        tool_name="test_tool",
        tool_description="A test tool",
        input_schema={},
    )
    result = await adapter.handler({"arg1": "value1"})
    mock_session.call_tool.assert_called_once_with("test_tool", arguments={"arg1": "value1"})
    assert result["output"] == "result text"
    assert result["status"] == "success"


async def test_mcp_skill_adapter_handler_error():
    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(side_effect=Exception("connection lost"))

    adapter = MCPSkillAdapter(
        session=mock_session,
        tool_name="test_tool",
        tool_description="A test tool",
        input_schema={},
    )
    with pytest.raises(ConnectorError, match="connection lost"):
        await adapter.handler({"arg1": "value1"})


async def test_mcp_skill_adapter_handler_preserves_atlas_errors():
    """AtlasError subclasses should propagate without being wrapped in ConnectorError."""
    from atlas.contracts.errors import SkillValidationError
    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(
        side_effect=SkillValidationError("bad input schema")
    )

    adapter = MCPSkillAdapter(
        session=mock_session,
        tool_name="test_tool",
        tool_description="A test tool",
        input_schema={},
    )
    with pytest.raises(SkillValidationError, match="bad input schema"):
        await adapter.handler({"arg1": "value1"})


def _make_tool(name: str, description: str, input_schema: dict) -> MagicMock:
    """Create a mock MCP tool with proper name attribute."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = input_schema
    return tool


def test_mcp_bridge_register_tools(registry):
    mock_session = MagicMock()
    bridge = MCPBridge(registry=registry)
    tools = [
        _make_tool("tool_a", "Tool A desc", {"type": "object"}),
        _make_tool("tool_b", "Tool B desc", {"type": "object"}),
    ]
    bridge.register_tools(mock_session, tools, server_name="test-server")
    all_skills = registry.list_all()
    skill_ids = {s.skill_id for s in all_skills}
    assert "mcp.tool_a" in skill_ids
    assert "mcp.tool_b" in skill_ids


def test_mcp_bridge_unregister_server(registry):
    mock_session = MagicMock()
    bridge = MCPBridge(registry=registry)
    tools = [
        _make_tool("tool_a", "Tool A desc", {"type": "object"}),
    ]
    bridge.register_tools(mock_session, tools, server_name="test-server")
    assert len(registry.list_all()) == 1

    bridge.unregister_server("test-server")
    assert len(registry.list_all()) == 0


def test_mcp_bridge_register_tools_idempotent_on_reconnect(registry):
    """Re-registering tools for the same server should not create duplicates."""
    mock_session = MagicMock()
    bridge = MCPBridge(registry=registry)
    tools = [
        _make_tool("tool_a", "Tool A desc", {"type": "object"}),
    ]

    # First registration
    bridge.register_tools(mock_session, tools, server_name="test-server")
    assert len(registry.list_all()) == 1

    # Second registration (simulating reconnect)
    bridge.register_tools(mock_session, tools, server_name="test-server")
    assert len(registry.list_all()) == 1

    # Verify no duplicate skill IDs in server tracking
    servers = bridge.list_servers()
    assert len(servers["test-server"]) == 1, (
        f"Expected 1 skill ID, got {len(servers['test-server'])}: {servers['test-server']}"
    )

    # Unregister should clean up without errors
    bridge.unregister_server("test-server")
    assert len(registry.list_all()) == 0
