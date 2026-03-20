from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Set, Any

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    GOOGLE_API_KEY: str
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    DATABASE_URL: str

    # Security configuration
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # CORS — set specific origins in production (e.g. "https://app.example.com,https://admin.example.com")
    # Wildcard "*" disables credentials automatically (browser enforces this).
    CORS_ORIGINS: List[str] = ["*"]

    # Supported models
    ALLOWED_MODELS_LIST: List[str] = [
        # Google Gemini
        "gemini-3.1-pro",        # Balanced / High capability
        "gemini-3-flash",        # Fast / Economical (no 3.1 version)
        "gemini-3.1-flash-lite", # Edge / Ultra Low Latency
        # OpenAI GPT-5.4 (effort: low / medium / high via Responses API)
        "gpt-5.4-mini",          # Low reasoning effort
        "gpt-5.4-medium",        # Medium reasoning effort
        "gpt-5.4-high",          # High reasoning effort
        # Anthropic Claude
        "claude-sonnet-4-6",     # Sonnet 4.6 — balanced
        "claude-haiku-4-5",      # Haiku 4.5 — fast / economical
    ]

    # Pre-computed set for O(1) lookup
    ALLOWED_MODELS: Set[str] = set()

    def __init__(self, **values: Any):
        super().__init__(**values)
        self.ALLOWED_MODELS = set(self.ALLOWED_MODELS_LIST)

settings = Settings()