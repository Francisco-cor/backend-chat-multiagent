import logging
import asyncio
from typing import Dict, Any

import httpx

from app.tools.base import Tool

logger = logging.getLogger(__name__)


class FetchUrlTool(Tool):
    name = "fetch_url"
    description = "Fetch content from a URL and return text preview."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "max_length": {"type": "integer", "description": "Max chars to return", "minimum": 100, "maximum": 5000, "default": 2000},
        },
        "required": ["url"],
    }

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> str:
        self.validate(args)
        url = args["url"]
        max_len = args.get("max_length", 2000)
        # Basic allowlist: block private IPs, file://, etc.
        if url.startswith("file://") or "169.254." in url or url.startswith("http://localhost"):
            return "Error: URL not allowed for security reasons"
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "ClaraBot/1.0"})
                resp.raise_for_status()
                text = resp.text
                if len(text) > max_len:
                    text = text[:max_len] + "...[truncated]"
                return text
        except httpx.HTTPStatusError as e:
            return f"Error: HTTP {e.response.status_code} for {url}"
        except Exception as e:
            return f"Error fetching {url}: {str(e)[:500]}"
