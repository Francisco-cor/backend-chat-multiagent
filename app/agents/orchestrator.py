import logging
from collections.abc import AsyncGenerator
from typing import Any

from app.agents.base import Agent
from app.agents.guardrails import apply_guardrails, validate_agent_output
from app.agents.registry import registry
from app.agents.scratchpad import Scratchpad

logger = logging.getLogger(__name__)


class SupervisorOrchestrator:
    """
    Routes prompt to appropriate agents and synthesizes result.
    Strategies: sequential (researcher -> analyst -> clara), parallel, direct.
    """

    def __init__(self):
        self.registry = registry

    def _classify_intent(self, prompt: str) -> list[str]:
        lower = prompt.lower()
        needs_research = any(k in lower for k in ["investiga", "search", "busca", "research", "google", "grounding", "what is", "who is", "noticias"])
        needs_analysis = any(k in lower for k in ["analiza", "analysis", "code", "código", "python", "data", "calcula", "compare"])
        needs_critic = any(k in lower for k in ["revisa", "critic", "review", "validate"])

        # If prompt explicitly says "orchestrate" with multiple intents, do sequential
        if "investiga" in lower and "analiza" in lower:
            return ["researcher", "analyst", "clara"]
        if needs_research and needs_analysis:
            return ["researcher", "analyst", "clara"]
        if needs_research:
            return ["researcher", "clara"]  # researcher then supervisor synthesizes
        if needs_analysis:
            return ["analyst", "clara"]
        if needs_critic:
            return ["clara", "critic"]
        # Default: clara direct
        return ["clara"]

    async def orchestrate(
        self,
        prompt: str,
        history: list[Any],
        context: dict[str, Any] | None = None,
        strategy: str = "auto",
    ) -> tuple[str, list[dict[str, str]]]:
        """
        Returns (final_reply, trace) where trace is list of {agent, output}
        """
        context = context or {}
        scratchpad = Scratchpad()
        trace: list[dict[str, str]] = []

        # Guardrail on input
        allowed, sanitized_prompt = apply_guardrails("supervisor", prompt)
        if not allowed:
            return sanitized_prompt, [{"agent": "guardrail", "output": sanitized_prompt}]
        prompt = sanitized_prompt

        # Determine agents
        if strategy == "auto":
            agent_names = self._classify_intent(prompt)
        elif strategy == "sequential":
            agent_names = ["researcher", "analyst", "clara"]
        elif strategy == "parallel":
            agent_names = ["researcher", "analyst"]
        elif strategy == "direct":
            agent_names = ["clara"]
        else:
            # comma separated custom list
            agent_names = [a.strip() for a in strategy.split(",") if a.strip()]

        logger.info(f"Orchestrator: strategy={strategy} agents={agent_names}")

        # Handle parallel strategy
        if strategy == "parallel":
            import asyncio

            agents = [self.registry.get(n) for n in agent_names if self.registry.get(n)]
            tasks = [self._run_agent(a, prompt, history, scratchpad, context) for a in agents if a]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for agent, res in zip(agents, results):
                if isinstance(res, Exception):
                    logger.error(f"Parallel agent {agent.name} failed: {res}")
                    trace.append({"agent": agent.name, "output": f"error: {res}", "error": True})
                else:
                    # validate output
                    ok, validated = validate_agent_output(agent.name, res)
                    if not ok:
                        res = validated
                    trace.append({"agent": agent.name, "output": res})
            # Synthesize with clara if not already included
            if "clara" not in agent_names:
                clara = self.registry.get("clara")
                if clara:
                    synth_prompt = f"Synthesize these parallel results into a final answer for: {prompt}\nResults: {scratchpad.summary()}"
                    final = await self._run_agent(clara, synth_prompt, history, scratchpad, context)
                    trace.append({"agent": "clara", "output": final})
                    return final, trace
            # If no synthesize, join results
            joined = "\n\n".join([f"[{t['agent']}] {t['output']}" for t in trace])
            return joined, trace

        # Sequential (default)
        final_reply = ""
        for name in agent_names:
            agent = self.registry.get(name)
            if not agent:
                logger.warning(f"Agent {name} not found, skipping")
                continue
            # For intermediate agents, pass enriched prompt; for final clara, synthesize
            if name == "clara" and len(agent_names) > 1 and final_reply == "":
                # Clara synthesizing previous results
                synth_prompt = f"Synthesize the following information to answer: {prompt}\nContext from other agents:\n{scratchpad.summary()}"
                out = await self._run_agent(agent, synth_prompt, history, scratchpad, context)
            else:
                out = await self._run_agent(agent, prompt, history, scratchpad, context)
            # Guardrail output
            ok, validated = validate_agent_output(agent.name, out)
            if not ok:
                out = validated
            trace.append({"agent": agent.name, "output": out})
            final_reply = out
            # Update prompt for next agent to include previous output (handoff)
            prompt = f"Previous agent {name} output: {out}\n\nOriginal request: {prompt}"

        return final_reply, trace

    async def _run_agent(
        self, agent: Agent, prompt: str, history: list[Any], scratchpad: Scratchpad, context: dict[str, Any]
    ) -> str:
        allowed, sanitized = apply_guardrails(agent.name, prompt)
        if not allowed:
            return sanitized
        prompt = sanitized
        # History window per agent
        h = agent.history_window(history)
        return await agent.run(prompt, h, scratchpad, context)

    async def orchestrate_stream(
        self,
        prompt: str,
        history: list[Any],
        context: dict[str, Any] | None = None,
        strategy: str = "auto",
    ) -> AsyncGenerator[dict[str, str], None]:
        """
        Streams events: {agent, delta, done}
        For simplicity, streams final agent's output chunk by chunk, but emits per-agent start/done events.
        """
        context = context or {}
        scratchpad = Scratchpad()
        trace_agents = self._classify_intent(prompt) if strategy == "auto" else [a.strip() for a in strategy.split(",")] if strategy not in ("sequential", "parallel", "direct", "auto") else (["researcher", "analyst", "clara"] if strategy == "sequential" else ["researcher", "analyst"] if strategy == "parallel" else ["clara"])

        for name in trace_agents:
            agent = self.registry.get(name)
            if not agent:
                continue
            yield {"agent": name, "event": "start", "delta": ""}
            # For streaming, we need provider's generate_stream; for LLMAgent we simulate chunking if not streaming
            # Check if agent has streaming capability: try to call generate_stream via provider
            # For now, run agent and then chunk its output
            out = await self._run_agent(agent, prompt, history, scratchpad, context)
            # Chunk output into words for streaming simulation
            words = out.split()
            for w in words:
                yield {"agent": name, "event": "delta", "delta": w + " "}
            yield {"agent": name, "event": "done", "delta": ""}
            prompt = f"Previous {name}: {out}\nOriginal: {prompt}"
            if name == trace_agents[-1]:
                # final done
                yield {"agent": "orchestrator", "event": "done", "delta": ""}
