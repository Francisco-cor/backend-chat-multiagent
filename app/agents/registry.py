
from app.agents.base import Agent, AgentConfig, LLMAgent

# Seed configs
CLARA_CONFIG = AgentConfig(
    name="clara",
    description="Clara — asistente general, router y supervisor. Concisa, proactiva.",
    system_prompt="You are Clara, a professional virtual assistant. Communicate in Spanish or English, be concise and helpful. You supervise other agents and synthesize their outputs.",
    model="gemini-3.1-pro",
    temperature=0.7,
    max_history=15,
    tools=[],
)

RESEARCHER_CONFIG = AgentConfig(
    name="researcher",
    description="Researcher — especialista en búsqueda y síntesis con grounding.",
    system_prompt="You are Researcher, an expert at gathering information via Google Search grounding and synthesizing findings with citations. Be factual and concise.",
    model="gemini-3.1-pro",
    temperature=0.5,
    max_history=10,
    tools=["web_search"],
)

ANALYST_CONFIG = AgentConfig(
    name="analyst",
    description="Analyst — especialista en análisis, código y datos.",
    system_prompt="You are Analyst, an expert at data analysis, code execution and structured reasoning. Provide clear, step-by-step analysis.",
    model="gpt-5.4-mini",
    temperature=0.5,
    max_history=10,
    tools=["code_exec", "db_query", "fetch_url"],
)

CRITIC_CONFIG = AgentConfig(
    name="critic",
    description="Critic — revisor y validador de respuestas.",
    system_prompt="You are Critic, a careful reviewer. Check answers for correctness, bias and completeness. Suggest improvements.",
    model="claude-haiku-4-5",
    temperature=0.3,
    max_history=5,
    tools=[],
)


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, Agent] = {}
        self._register_defaults()

    def _register_defaults(self):
        for cfg in [CLARA_CONFIG, RESEARCHER_CONFIG, ANALYST_CONFIG, CRITIC_CONFIG]:
            self.register(LLMAgent(cfg))

    def register(self, agent: Agent):
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent | None:
        return self._agents.get(name.lower())

    def list_agents(self) -> list[Agent]:
        return list(self._agents.values())

    def list_configs(self) -> list[AgentConfig]:
        return [a.config for a in self._agents.values()]


# Global singleton
registry = AgentRegistry()
