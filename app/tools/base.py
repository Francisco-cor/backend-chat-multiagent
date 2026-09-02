import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict

import jsonschema

logger = logging.getLogger(__name__)


class Tool(ABC):
    name: str = ""
    description: str = ""
    # JSON Schema for arguments
    parameters: Dict[str, Any] = {}

    def __init__(self):
        if not self.name:
            raise ValueError("Tool must have a name")
        # Ensure schema has type object
        if not self.parameters:
            self.parameters = {"type": "object", "properties": {}, "required": []}
        if "type" not in self.parameters:
            self.parameters["type"] = "object"

    def validate(self, args: Dict[str, Any]) -> None:
        jsonschema.validate(instance=args, schema=self.parameters)

    @abstractmethod
    async def execute(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> str:
        pass

    def to_openai_tool(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_tool(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    def to_gemini_tool(self) -> Dict[str, Any]:
        # Gemini uses FunctionDeclaration
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def __repr__(self):
        return f"<Tool {self.name}>"
