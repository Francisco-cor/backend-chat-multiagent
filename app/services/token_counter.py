import re

# Cost per 1K tokens (USD) — simplified, adjust to real pricing
COST_PER_1K_TOKENS = {
    # Gemini 3.x
    "gemini-3.1-pro": 0.0025,
    "gemini-3-flash": 0.0005,
    "gemini-3.1-flash-lite": 0.0002,
    # GPT 5.4
    "gpt-5.4-mini": 0.001,
    "gpt-5.4-medium": 0.003,
    "gpt-5.4-high": 0.006,
    "gpt-5.4": 0.003,
    # Claude
    "claude-sonnet-4-6": 0.003,
    "claude-haiku-4-5": 0.0008,
    "claude-haiku-4-5-20251001": 0.0008,
}

DEFAULT_COST_PER_1K = 0.002


def count_tokens(text: str) -> int:
    """
    Approximate token count.
    Tries tiktoken if available, else falls back to heuristic: ~4 chars per token.
    """
    if not text:
        return 0
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        # Fallback: 1 token ~ 4 chars or ~0.75 words
        # Use max of char-based and word-based to be safe
        char_tokens = max(1, len(text) // 4)
        word_tokens = len(text.split())
        # Average heuristic
        return max(char_tokens, word_tokens)


def estimate_cost(tokens: int, model: str) -> float:
    model_lower = (model or "").lower()
    # Exact match first, then prefix
    for key, cost in COST_PER_1K_TOKENS.items():
        if model_lower == key.lower():
            return (tokens / 1000) * cost
    for key, cost in COST_PER_1K_TOKENS.items():
        if model_lower.startswith(key.lower().split("-")[0]):
            return (tokens / 1000) * cost
    return (tokens / 1000) * DEFAULT_COST_PER_1K


def count_message_tokens(content: str, role: str = "user") -> int:
    # Add small overhead per message (role + formatting)
    return count_tokens(content) + 4
