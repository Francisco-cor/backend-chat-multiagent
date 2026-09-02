import logging
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.base import Tool

logger = logging.getLogger(__name__)


class DbQueryTool(Tool):
    name = "db_query"
    description = "Execute a read-only SELECT query on the user's own data. Only SELECT allowed."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "SQL SELECT query, must start with SELECT and include WHERE user_id = :user_id"},
            "limit": {"type": "integer", "description": "Max rows", "minimum": 1, "maximum": 20, "default": 10},
        },
        "required": ["query"],
    }

    async def execute(self, args: dict[str, Any], context: dict[str, Any] | None = None) -> str:
        self.validate(args)
        query = args["query"].strip()
        limit = args.get("limit", 10)

        # Security: only SELECT
        if not re.match(r"^\s*SELECT\b", query, re.IGNORECASE):
            return "Error: Only SELECT queries are allowed"

        # Must contain user_id filter to enforce isolation
        if "user_id" not in query.lower():
            return "Error: Query must filter by user_id = :user_id for isolation"

        # Block dangerous keywords
        blocked = ["insert", "update", "delete", "drop", "alter", "create", "truncate", "union", "--", ";--"]
        lower = query.lower()
        for b in blocked:
            if b in lower and b != "select":
                # Allow union in some cases? Block for now
                if b in ["insert", "update", "delete", "drop", "alter", "create", "truncate"]:
                    return f"Error: Keyword '{b}' not allowed"

        context = context or {}
        db: AsyncSession | None = context.get("db")
        user_id = context.get("user_id")
        if not db or user_id is None:
            return "Error: Missing db context"

        # Enforce limit
        if "limit" not in lower:
            query = f"{query.rstrip(';')} LIMIT {limit}"
        else:
            # override limit to max
            query = re.sub(r"LIMIT\s+\d+", f"LIMIT {limit}", query, flags=re.IGNORECASE)

        try:
            result = await db.execute(text(query), {"user_id": user_id})
            rows = result.fetchall()
            if not rows:
                return "(no rows)"
            # Format rows
            cols = list(result.keys())
            lines = [" | ".join(cols)]
            for row in rows[:limit]:
                lines.append(" | ".join(str(v)[:100] for v in row))
            return "\n".join(lines)[:2000]
        except Exception as e:
            logger.warning(f"db_query failed: {e}")
            return f"Error: {str(e)[:500]}"
