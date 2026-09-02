import logging

from app.mcp.client import MCPClient
from app.tools.registry import tool_registry

logger = logging.getLogger(__name__)


class MCPRegistry:
    def __init__(self):
        self.servers: dict[str, MCPClient] = {}

    def add_server(self, name: str, url: str, transport: str = "sse"):
        self.servers[name] = MCPClient(name, url, transport)
        logger.info(f"MCP server added: {name} -> {url}")

    async def load_tools(self):
        for name, client in self.servers.items():
            tools = await client.list_tools()
            for tdef in tools:
                try:
                    proxy = client.to_tool(tdef)
                    tool_registry.register(proxy)
                    logger.info(f"MCP tool registered: {proxy.name} from {name}")
                except Exception as e:
                    logger.warning(f"Failed to register MCP tool {tdef}: {e}")

    def list_servers(self) -> list[str]:
        return list(self.servers.keys())


mcp_registry = MCPRegistry()
