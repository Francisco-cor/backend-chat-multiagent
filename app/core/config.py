from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Set

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    GOOGLE_API_KEY: str
    OPENAI_API_KEY: str | None = None
    DATABASE_URL: str
    
    # Security configuration
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Supported models for the new google-genai API (2025 Standard)
    ALLOWED_MODELS_LIST: List[str] = [
        "gemini-2.5-pro",        # Balanced
        "gemini-2.5-flash",      # Fast / Economical
        "gemini-2.5-flash-lite", # Edge / Ultra Low Latency
        "gemini-3.0-pro-preview",# SOTA Experimental
        "gpt-5-low",
        "gpt-5-high"
    ]

    @property
    def ALLOWED_MODELS(self) -> Set[str]:
        """Returns the allowed models as a set for O(1) lookup."""
        return set(self.ALLOWED_MODELS_LIST)

settings = Settings()