from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentConfig:
    name: str
    description: str
    system_prompt: str
    model: str = "gemini-3.1-pro"
    temperature: float = 0.7
    max_history: int = 10
    tools: list[str] = field(default_factory=list)
    allow_handoff: bool = True


class Agent(ABC):
    def __init__(self, config: AgentConfig):
        self.config = config
        self.name = config.name

    @abstractmethod
    async def run(
        self,
        prompt: str,
        history: list[Any],
        scratchpad: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> str:
        pass

    def history_window(self, history: list[Any]) -> list[Any]:
        # Per-agent history window
        if self.config.max_history <= 0:
            return history
        return history[-self.config.max_history :]

    def __repr__(self):
        return f"<Agent {self.name} model={self.config.model}>"


class LLMAgent(Agent):
    """Simple LLM-backed agent that delegates to LLMProvider."""

    def __init__(self, config: AgentConfig):
        super().__init__(config)

    async def run(
        self,
        prompt: str,
        history: List[Any],
        scratchpad: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        from app.services.chat_service import ChatService
        from app.tools.registry import tool_registry

        agent_context = f"[{self.name}] {self.config.system_prompt}\n"
        if scratchpad:
            scratchpad_str = "\n".join([f"{k}: {v[:500]}" for k, v in scratchpad.items()])
            agent_context += f"\nScratchpad:\n{scratchpad_str}\n"
        enriched_prompt = f"{agent_context}\nUser: {prompt}"

        h = self.history_window(history)

        openai_client = context.get("openai_client") if context else None
        provider = ChatService.get_provider(self.config.model, openai_client)

        # Gather tools allowed for this agent
        allowed_tools = tool_registry.get_allowed(self.config.tools) if self.config.tools else []
        # Include global allowlist if configured
        from app.core.config import settings as cfg

        if cfg.TOOL_ALLOWLIST is not None:
            allowed_tools = [t for t in allowed_tools if t.name in cfg.TOOL_ALLOWLIST]

        # Filter to only pass if there are tools (or search)
        tools_to_pass = allowed_tools if allowed_tools else None

        reply = await provider.generate(
            prompt=enriched_prompt,
            history=h,
            image_data=context.get("image_data") if context else None,
            file_data=context.get("file_data") if context else None,
            use_search="search" in self.config.tools,
            tools=tools_to_pass,
            tool_context=context,
        )
        scratchpad[self.name] = reply
        return reply
