from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Set, Any, Dict

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
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_MINUTES: int = 15

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters (got %d)" % len(v))
        weak = {"secret", "changeme", "password", "test", "123456", "default", "secretkey"}
        if v.lower() in weak:
            raise ValueError("SECRET_KEY is too weak")
        return v

    @field_validator("ALGORITHM")
    @classmethod
    def validate_algorithm(cls, v: str) -> str:
        allowed = {"HS256", "HS384", "HS512", "RS256"}
        if v not in allowed:
            raise ValueError(f"ALGORITHM must be one of {allowed}")
        return v

    # CORS — set specific origins in production (e.g. "https://app.example.com,https://admin.example.com")
    # Wildcard "*" disables credentials automatically (browser enforces this).
    CORS_ORIGINS: List[str] = ["*"]

    # Maximum number of past messages loaded as context for each LLM request
    HISTORY_LIMIT: int = 15

    # Set to false for plain-text logs during local development
    JSON_LOGS: bool = True

    # Maximum size of uploaded files in MB (enforced before reading into memory)
    MAX_UPLOAD_SIZE_MB: int = 10

    # Timeout in seconds for LLM API calls (applies to non-streaming generate())
    LLM_TIMEOUT_SECONDS: int = 60

    # Orchestrator
    ORCHESTRATOR_ENABLED: bool = True
    ORCHESTRATOR_STRATEGY: str = "auto"  # auto | sequential | parallel | direct

    # RAG / Embeddings
    EMBEDDING_PROVIDER: str = "dummy"  # dummy | openai | gemini
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 64
    RAG_TOP_K: int = 4
    RAG_CHUNK_SIZE: int = 512
    RAG_CHUNK_OVERLAP: int = 50

    # Tools
    TOOL_ALLOWLIST: List[str] | None = None  # None = all, else list of allowed tool names
    MAX_TOOL_ITERATIONS: int = 5

    # MCP
    MCP_SERVERS: List[Dict[str, Any]] = []  # e.g. [{"name": "my_server", "url": "http://localhost:8001", "transport": "sse"}]

    # Streaming / Realtime (Fase 7)
    SSE_HEARTBEAT_SECONDS: int = 15
    WS_PING_INTERVAL: int = 30

    # File / S3 (Fase 7.4)
    S3_ENDPOINT: str | None = None
    S3_ACCESS_KEY: str | None = None
    S3_SECRET_KEY: str | None = None
    S3_BUCKET: str | None = None
    S3_REGION: str = "us-east-1"

    # Infra / Redis (Fase 8)
    REDIS_URL: str | None = None
    # Optional DB pool size tuning
    DB_POOL_SIZE: int = 10

    # Platform — Quotas & Billing (Fase 9)
    QUOTA_FREE_TOKENS: int = 100_000  # per month
    QUOTA_PRO_TOKENS: int = 1_000_000
    QUOTA_ENTERPRISE_TOKENS: int = 10_000_000
    # soft limit 80% triggers warning header, hard limit denies
    QUOTA_SOFT_PCT: float = 0.8
    STRIPE_WEBHOOK_SECRET: str | None = None
    BILLING_ENABLED: bool = False

    # Rate limit (Fase 9.1) — per-principal sliding window fallback
    CHAT_RATE_LIMIT: str = "5/minute"
    API_KEY_RATE_LIMIT: str = "60/minute"

    # Tracing (Fase 11.1)
    OTEL_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://otel-collector:4317"
    OTEL_SERVICE_NAME: str = "backend-chat-multiagent"

    # Cache (Fase 11.2)
    CACHE_ENABLED: bool = True
    CACHE_TTL_SECONDS: int = 3600
    CACHE_EMBEDDING_TTL: int = 86400
    LLM_CACHE_TTL: int = 600

    # Retention / GDPR (Fase 11.5)
    RETENTION_DAYS: int = 365
    GDPR_RETENTION_DAYS: int = 30

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