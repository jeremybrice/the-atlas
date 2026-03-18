"""MCP Bridge — connects to MCP servers and registers tools as ATLAS skills."""

import logging
from dataclasses import dataclass
from typing import Any

from atlas.contracts.errors import AtlasError, ConnectorError
from atlas.contracts.types import RiskLevel
from atlas.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


@dataclass
class MCPSkillAdapter:
    """Wraps an MCP tool as an ATLAS skill handler."""

    session: Any  # MCP ClientSession
    tool_name: str
    tool_description: str
    input_schema: dict[str, Any]
    risk_level: RiskLevel = RiskLevel.HIGH

    @property
    def skill_id(self) -> str:
        return f"mcp.{self.tool_name}"

    @property
    def name(self) -> str:
        return self.tool_name

    @property
    def description(self) -> str:
        return self.tool_description

    async def handler(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await self.session.call_tool(self.tool_name, arguments=params)
            # Extract text content from MCP result
            output = ""
            if hasattr(result, "content") and result.content:
                texts = [c.text for c in result.content if hasattr(c, "text")]
                output = "\n".join(texts)
            return {"status": "success", "output": output}
        except AtlasError:
            raise
        except Exception as e:
            logger.error("MCP tool %s failed: %s", self.tool_name, e)
            raise ConnectorError(f"MCP tool {self.tool_name} failed: {e}", cause=e)


class MCPBridge:
    """Manages MCP server connections and tool registration."""

    def __init__(self, registry: SkillRegistry):
        self._registry = registry
        self._server_skills: dict[str, list[str]] = {}  # server_name -> [skill_ids]

    def register_tools(self, session: Any, tools: list, server_name: str) -> list[str]:
        """Register MCP tools as ATLAS skills. Returns list of registered skill IDs."""
        # Unregister existing tools for this server first (idempotent on reconnect)
        if server_name in self._server_skills:
            self.unregister_server(server_name)

        registered = []
        self._server_skills[server_name] = []

        for tool in tools:
            adapter = MCPSkillAdapter(
                session=session,
                tool_name=tool.name,
                tool_description=tool.description or f"MCP tool: {tool.name}",
                input_schema=getattr(tool, "inputSchema", {}) or {},
            )
            self._registry.register(
                skill_id=adapter.skill_id,
                name=adapter.name,
                description=adapter.description,
                handler=adapter.handler,
                risk_level="high",
                tags=["mcp", server_name],
            )
            self._server_skills[server_name].append(adapter.skill_id)
            registered.append(adapter.skill_id)
            logger.info(
                "Registered MCP tool: %s from %s", adapter.skill_id, server_name
            )

        return registered

    def unregister_server(self, server_name: str) -> None:
        """Unregister all skills from a given MCP server."""
        skill_ids = self._server_skills.pop(server_name, [])
        for skill_id in skill_ids:
            self._registry.unregister(skill_id)
            logger.info("Unregistered MCP tool: %s", skill_id)

    def list_servers(self) -> dict[str, list[str]]:
        """Return map of server_name -> registered skill IDs."""
        return dict(self._server_skills)
