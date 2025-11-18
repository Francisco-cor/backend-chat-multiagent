from typing import Optional
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    """
    Payload de entrada para /api/v1/chat/ (JSON).
    """
    session_id: str = Field(..., min_length=1, description="Identificador único de la sesión de chat")
    prompt: str = Field(..., min_length=1, description="Mensaje del usuario")
    
    # Si no se envía, el backend usará el default configurado (gemini-2.5-pro)
    model: Optional[str] = Field(None, description="Ej: gemini-2.5-pro, gemini-2.5-flash, gpt-5-low")
    
    # NUEVO CAMPO: Activa Google Grounding (Búsqueda web)
    use_search: bool = Field(False, description="Si es True, permite al modelo buscar en Google.")

    # Campos para multimodalidad (imágenes)
    image_base64: Optional[str] = None
    image_mime_type: Optional[str] = None

    # Campos para archivos generales
    file_base64: Optional[str] = None
    file_mime_type: Optional[str] = None


class ChatResponse(BaseModel):
    """
    Respuesta estándar del backend.
    """
    session_id: str
    reply: str
    model_used: str  # Devolvemos qué modelo se usó realmente