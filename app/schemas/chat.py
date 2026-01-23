from typing import Optional
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    """
    Input payload for /api/v1/chat/ (JSON).
    """
    session_id: str = Field(..., min_length=1, description="Unique identifier for the chat session")
    prompt: str = Field(..., min_length=1, description="The user's message")
    
    # If not provided, the backend uses the configured default (gemini-2.5-pro)
    model: Optional[str] = Field(None, description="Example: gemini-2.5-pro, gemini-2.5-flash, gpt-5-low")
    
    # Enable Google Grounding (Web search)
    use_search: bool = Field(False, description="If True, allows the model to perform a Google Search.")

    # Multimodal fields (images)
    image_base64: Optional[str] = None
    image_mime_type: Optional[str] = None

    # Fields for general files
    file_base64: Optional[str] = None
    file_mime_type: Optional[str] = None


class ChatResponse(BaseModel):
    """
    Standard chat response from the backend.
    """
    session_id: str
    reply: str
    model_used: str  # Returns which model was actually utilized