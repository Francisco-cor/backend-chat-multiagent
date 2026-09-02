import asyncio
import logging
import time
from typing import Dict, Any

from app.tools.base import Tool

logger = logging.getLogger(__name__)


class CodeExecTool(Tool):
    name = "code_exec"
    description = "Execute Python code in a sandboxed environment. Use for calculations, data processing, simple algorithms."
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute. Use print() to output results."},
            "timeout": {"type": "integer", "description": "Timeout seconds", "minimum": 1, "maximum": 10, "default": 5},
        },
        "required": ["code"],
    }

    async def execute(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> str:
        self.validate(args)
        code = args["code"]
        timeout = args.get("timeout", 5)

        # Security: block dangerous imports and operations
        blocked = ["import os", "import sys", "import subprocess", "open(", "__import__", "eval(", "exec(", "socket", "requests"]
        for b in blocked:
            if b in code:
                return f"Error: Blocked operation '{b}' not allowed in sandbox"

        if "while True" in code or "for i in range(100000" in code:
            return "Error: Potential infinite loop blocked"

        def _run():
            import io
            import sys
            import contextlib

            # Restricted builtins
            allowed_builtins = {
                "print": print,
                "range": range,
                "len": len,
                "str": str,
                "int": int,
                "float": float,
                "list": list,
                "dict": dict,
                "set": set,
                "sum": sum,
                "min": min,
                "max": max,
                "sorted": sorted,
                "enumerate": enumerate,
                "zip": zip,
                "abs": abs,
                "round": round,
                "pow": pow,
            }
            output = io.StringIO()
            try:
                with contextlib.redirect_stdout(output):
                    # Provide limited globals
                    exec(code, {"__builtins__": allowed_builtins}, {})
                return output.getvalue() or "(no output)"
            except Exception as e:
                return f"Error: {type(e).__name__}: {e}"

        try:
            result = await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout)
            if len(result) > 2000:
                result = result[:2000] + "...[truncated]"
            return result.strip() or "(executed with no output)"
        except asyncio.TimeoutError:
            return "Error: Code execution timed out"
        except Exception as e:
            return f"Error: {e}"
