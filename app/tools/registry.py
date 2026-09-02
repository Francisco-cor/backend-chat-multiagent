from typing import Dict, List

from app.tools.base import Tool


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> List[Tool]:
        return list(self._tools.values())

    def list_names(self) -> List[str]:
        return list(self._tools.keys())

    def get_allowed(self, allowlist: List[str] | None) -> List[Tool]:
        if not allowlist:
            return self.list()
        return [t for n, t in self._tools.items() if n in allowlist]

    def clear(self):
        self._tools.clear()


# Global registry
tool_registry = ToolRegistry()


def load_builtin_tools():
    from app.tools.builtin.web_search import WebSearchTool
    from app.tools.builtin.fetch_url import FetchUrlTool
    from app.tools.builtin.code_exec import CodeExecTool
    from app.tools.builtin.db_query import DbQueryTool

    for cls in [WebSearchTool, FetchUrlTool, CodeExecTool, DbQueryTool]:
        try:
            tool_registry.register(cls())
        except Exception:
            pass
