import base64
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request, Form, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService
from app.db.session import get_db
from app.core.config import settings
from app.core.rate_limit import limiter
from app.api import deps
from app.db.models import User

router = APIRouter()
logger = logging.getLogger(__name__)

def _validate_model_name(model_input: Optional[str]) -> str:
    """
    Normalizes and validates the requested model against allowed configuration.
    """
    m = (model_input or "gemini-2.5-pro").strip().lower()
    
    # Check if the model is in the allowed set (Optimized lookup)
    if m not in settings.ALLOWED_MODELS:
        # Warning log for models not explicitly in ALLOWED_MODELS
        logger.warning(f"Requested model '{m}' is not in explicit ALLOWED_MODELS.")
    
    return m

@router.post("/", response_model=ChatResponse)
@limiter.limit("5/minute")
async def handle_chat_json(
    request: Request,
    request_data: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Main endpoint for chat via JSON.
    Supports: Text, Images (base64), Files (base64), and Grounding (use_search).
    """
    normalized_model = _validate_model_name(request_data.model)

    # Prepare image data if present
    image_data = None
    if request_data.image_base64 and request_data.image_mime_type:
        image_data = {
            "data": request_data.image_base64, 
            "mime_type": request_data.image_mime_type
        }

    # Prepare file data if present
    file_data = None
    if request_data.file_base64 and request_data.file_mime_type:
        file_data = {
            "data": request_data.file_base64,
            "mime_type": request_data.file_mime_type
        }

    try:
        # Delegate logic to the orchestrator service
        reply = await ChatService.process_chat(
            session_id=request_data.session_id,
            prompt=request_data.prompt,
            model_name=normalized_model,
            db=db,
            openai_client=getattr(request.app.state, "openai_client", None),
            image_data=image_data,
            file_data=file_data,
            use_search=request_data.use_search
        )

        return ChatResponse(
            session_id=request_data.session_id, 
            reply=reply, 
            model_used=normalized_model
        )

    except ValueError as ve:
        # Business validation errors
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.exception("Error processing JSON chat")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@router.post("/upload", response_model=ChatResponse)
@limiter.limit("5/minute")
async def handle_chat_with_upload(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    session_id: str = Form(...),
    prompt: str = Form(...),
    model: Optional[str] = Form(None),
    use_search: bool = Form(False),
    file: UploadFile = File(None),
):
    """
    Endpoint for chat with binary file upload (multipart/form-data).
    """
    normalized_model = _validate_model_name(model)

    image_data = None
    file_data = None

    if file:
        try:
            # Run blocking I/O and CPU operations in threads
            contents = await file.read()
            b64_encoded = await asyncio.to_thread(lambda: base64.b64encode(contents).decode("utf-8"))
            mime_type = file.content_type or "application/octet-stream"

            if mime_type.startswith("image/"):
                image_data = {"data": b64_encoded, "mime_type": mime_type}
            else:
                file_data = {"data": b64_encoded, "mime_type": mime_type}
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Error reading uploaded file: {e}")

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
        logger.exception("Error processing Upload chat")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")
