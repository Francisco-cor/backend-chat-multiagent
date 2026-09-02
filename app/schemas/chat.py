from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

class ChatRequest(BaseModel):
    """
    Input payload for /api/v1/chat/ (JSON).

    Example:
    ```json
    {"session_id":"my-session-1","prompt":"Hello Clara, investiga...","model":"gemini-3.1-pro","use_search":false}
    ```
    """
    session_id: str = Field(..., min_length=1, max_length=128, description="Unique identifier for the chat session", examples=["sess_abc123", "my-session-1"])
    prompt: str = Field(..., min_length=1, max_length=32000, description="The user's message", examples=["Hello Clara", "Investiga X y analiza Y", "Summarize the file"])

    # If not provided, the backend uses the configured default (gemini-3.1-pro)
    model: Optional[str] = Field(None, description="LLM model id (must be in ALLOWED_MODELS)", examples=["gemini-3.1-pro", "gpt-5.4-mini", "claude-sonnet-4-6"])
    
    # Enable Google Grounding (Web search)
    use_search: bool = Field(False, description="If True, allows the model to perform a Google Search.", examples=[False, True])

    # Multimodal fields (images)
    image_base64: Optional[str] = Field(None, description="Base64-encoded image (PNG/JPEG)", examples=[None])
    image_mime_type: Optional[str] = Field(None, description="MIME for image_base64", examples=["image/png", "image/jpeg"])

    # Fields for general files
    file_base64: Optional[str] = Field(None, description="Base64-encoded file (text/* inlined)", examples=[None])
    file_mime_type: Optional[str] = Field(None, description="MIME for file_base64", examples=["text/plain", "application/pdf"])

    # Audio transcription (Fase 7.3)
    audio_base64: Optional[str] = Field(None, description="Base64-encoded audio (transcribed via Whisper)", examples=[None])
    audio_mime_type: Optional[str] = Field(None, description="MIME for audio_base64", examples=["audio/webm", "audio/wav"])


class ChatUsage(BaseModel):
    prompt_tokens: int = Field(..., examples=[12, 120])
    completion_tokens: int = Field(..., examples=[30, 250])
    total_tokens: int = Field(..., examples=[42, 370])
    cost_usd: float = Field(..., examples=[0.00012, 0.0015])
    model_config = ConfigDict(from_attributes=True)


class ChatResponse(BaseModel):
    """
    Standard chat response from the backend.

    Example:
    ```json
    {"session_id":"sess_abc123","reply":"Hola...","model_used":"gemini-3.1-pro","usage":{"prompt_tokens":12,"completion_tokens":30,"total_tokens":42,"cost_usd":0.00012}}
    ```
    """
    session_id: str = Field(..., examples=["sess_abc123"])
    reply: str = Field(..., examples=["Hello from Clara", "Aquí tienes el análisis..."])
    model_used: str = Field(..., examples=["gemini-3.1-pro"])  # Returns which model was actually utilized
    usage: Optional[ChatUsage] = Field(None, examples=[{"prompt_tokens":12,"completion_tokens":30,"total_tokens":42,"cost_usd":0.00012}])