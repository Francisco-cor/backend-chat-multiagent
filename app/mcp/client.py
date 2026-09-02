import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class MCPClient:
    def __init__(self, name: str, url: str, transport: str = "sse"):
        self.name = name
        self.url = url
        self.transport = transport

    async def list_tools(self) -> list[dict[str, Any]]:
        # For sse transport, GET /tools
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.url.rstrip('/')}/tools")
                resp.raise_for_status()
                data = resp.json()
                return data.get("tools", [])
        except Exception as e:
            logger.warning(f"MCP {self.name} list_tools failed: {e}")
            return []

    async def call_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.url.rstrip('/')}/tools/{tool_name}/call", json={"arguments": args}
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("result", str(data))
        except Exception as e:
            return f"MCP {self.name} error calling {tool_name}: {e}"

    def to_tool(self, tool_def: dict[str, Any]):
        # Convert MCP tool def to our Tool
        from app.tools.base import Tool

        class MCPProxyTool(Tool):
            name = f"{self.name}__{tool_def.get('name')}"
            description = tool_def.get("description", "")
            parameters = tool_def.get("inputSchema", {"type": "object", "properties": {}})

            async def execute(inner_self, args: dict[str, Any], context: dict[str, Any] | None = None) -> str:
                return await self.call_tool(tool_def.get("name"), args)

        return MCPProxyTool()
