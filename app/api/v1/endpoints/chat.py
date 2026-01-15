import base64
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request, Form, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService
from app.db.session import get_db
from app.core.config import settings
from app.api import deps
from app.db.models import User

router = APIRouter()
logger = logging.getLogger(__name__)

def _validate_model_name(model_input: Optional[str]) -> str:
    """
    Normaliza y valida el modelo solicitado contra la configuración permitida.
    """
    m = (model_input or "gemini-2.5-pro").strip().lower()
    
    # Si quieres ser estricto y rechazar modelos no listados en config:
    if m not in settings.ALLOWED_MODELS:
        # Opción A: Fallar
        # raise HTTPException(status_code=422, detail=f"Modelo '{m}' no permitido.")
        
        # Opción B (Recomendada por ahora): Loggear warning y dejar pasar (o hacer fallback)
        logger.warning(f"Modelo solicitado '{m}' no está en ALLOWED_MODELS explícitos.")
    
    return m

@router.post("/", response_model=ChatResponse)
async def handle_chat_json(
    request_data: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Endpoint principal para chat vía JSON.
    Soporta: Texto, Imágenes (base64), Archivos (base64) y Grounding (use_search).
    """
    normalized_model = _validate_model_name(request_data.model)

    # Preparar datos de imagen si existen
    image_data = None
    if request_data.image_base64 and request_data.image_mime_type:
        image_data = {
            "data": request_data.image_base64, 
            "mime_type": request_data.image_mime_type
        }

    # Preparar datos de archivo si existen
    file_data = None
    if request_data.file_base64 and request_data.file_mime_type:
        file_data = {
            "data": request_data.file_base64,
            "mime_type": request_data.file_mime_type
        }

    try:
        # Delegamos toda la lógica al servicio orquestador
        reply = await ChatService.process_chat(
            session_id=request_data.session_id,
            prompt=request_data.prompt,
            model_name=normalized_model,
            db=db,
            openai_client=getattr(request.app.state, "openai_client", None),
            image_data=image_data,
            file_data=file_data,
            use_search=request_data.use_search  # <--- Pasamos el flag al servicio
        )

        return ChatResponse(
            session_id=request_data.session_id, 
            reply=reply, 
            model_used=normalized_model
        )

    except ValueError as ve:
        # Errores de validación de negocio (ej. modelo desconocido en el provider)
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.exception("Error procesando chat JSON")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {e}")


@router.post("/upload", response_model=ChatResponse)
async def handle_chat_with_upload(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    session_id: str = Form(...),
    prompt: str = Form(...),
    model: Optional[str] = Form(None),
    use_search: bool = Form(False),  # <--- Se recibe como campo de formulario
    file: UploadFile = File(None),
):
    """
    Endpoint para chat con subida de archivos binarios (multipart/form-data).
    Ideal para Postman o clientes que suben archivos "drag & drop".
    """
    normalized_model = _validate_model_name(model)

    image_data = None
    file_data = None

    if file:
        try:
            contents = await file.read()
            b64_encoded = base64.b64encode(contents).decode("utf-8")
            mime_type = file.content_type or "application/octet-stream"

            if mime_type.startswith("image/"):
                image_data = {"data": b64_encoded, "mime_type": mime_type}
            else:
                file_data = {"data": b64_encoded, "mime_type": mime_type}
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Error leyendo el archivo subido: {e}")

    try:
        reply = await ChatService.process_chat(
            session_id=session_id,
            prompt=prompt,
            model_name=normalized_model,
            db=db,
            openai_client=getattr(request.app.state, "openai_client", None),
            image_data=image_data,
            file_data=file_data,
            use_search=use_search
        )

        return ChatResponse(
            session_id=session_id, 
            reply=reply, 
            model_used=normalized_model
        )

    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.exception("Error procesando chat Upload")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {e}")