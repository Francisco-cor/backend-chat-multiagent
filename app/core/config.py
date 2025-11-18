from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    GOOGLE_API_KEY: str
    OPENAI_API_KEY: str | None = None
    DATABASE_URL: str
    
    # Modelos soportados por la nueva API google-genai
    ALLOWED_MODELS: List[str] = [
        "gemini-2.5-pro",        # Balanceado
        "gemini-2.5-flash",      # Rápido / Económico
        "gemini-2.5-flash-lite", # Edge / Ultra Low Latency
        "gemini-3.0-pro-preview",# SOTA Experimental
        "gpt-5-low",
        "gpt-5-high"
    ]

settings = Settings()