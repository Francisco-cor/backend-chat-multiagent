from typing import Any


class Scratchpad(dict[str, Any]):
    """Shared memory across agents in a single orchestration."""

    def add(self, agent_name: str, content: str):
        self[agent_name] = content

    def summary(self, max_len: int = 2000) -> str:
        parts = []
        for k, v in self.items():
            snippet = v[:500] if isinstance(v, str) else str(v)[:500]
            parts.append(f"{k}: {snippet}")
        text = "\n".join(parts)
        return text[:max_len]

    def to_dict(self) -> dict[str, Any]:
        return dict(self)
