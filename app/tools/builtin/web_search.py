import logging
from typing import Any

from app.tools.base import Tool

logger = logging.getLogger(__name__)


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web for current information. Use when question requires up-to-date facts."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "num_results": {"type": "integer", "description": "Number of results (1-5)", "minimum": 1, "maximum": 5, "default": 3},
        },
        "required": ["query"],
    }

    async def execute(self, args: dict[str, Any], context: dict[str, Any] | None = None) -> str:
        self.validate(args)
        query = args["query"]
        num = args.get("num_results", 3)
        # For MVP, simulate search via grounding hint; in prod call Brave/SerpAPI
        # Return mocked structured result
        mock_results = [
            f"Result {i+1} for '{query}': This is a simulated search result about {query}. Relevant facts and recent news."
            for i in range(num)
        ]
        return "\n".join(mock_results)
