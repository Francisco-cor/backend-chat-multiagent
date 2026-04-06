import base64
import asyncio
import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request, Form, UploadFile, File
from fastapi.responses import StreamingResponse
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

# Regex for validating base64 strings (standard + URL-safe alphabets, padding optional)
_B64_RE = re.compile(r'^[A-Za-z0-9+/\-_]*={0,2}$')


def _validate_model_name(model_input: Optional[str]) -> str:
    """
    Normalizes and validates the requested model against allowed configuration.
    Raises HTTP 400 if the model is not in the allowed set.
    """
    m = (model_input or "gemini-2.5-pro").strip().lower()

    if m not in settings.ALLOWED_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{m}' is not allowed. Allowed: {sorted(settings.ALLOWED_MODELS)}"
        )

    return m


def _validate_base64(data: str, field_name: str) -> None:
    """Raises HTTP 422 if `data` is not a valid base64 string."""
    stripped = data.rstrip("=")
    if not _B64_RE.match(data) or len(stripped) % 4 > 2:
        raise HTTPException(status_code=422, detail=f"Invalid base64 encoding in field '{field_name}'")


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

    # Validate and prepare image data
    image_data = None
    if request_data.image_base64 and request_data.image_mime_type:
        _validate_base64(request_data.image_base64, "image_base64")
        image_data = {
            "data": request_data.image_base64,
            "mime_type": request_data.image_mime_type
        }

    # Validate and prepare file data
    file_data = None
    if request_data.file_base64 and request_data.file_mime_type:
        _validate_base64(request_data.file_base64, "file_base64")
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
            user_id=current_user.id,
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
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception:
        logger.exception("Error processing JSON chat")
        raise HTTPException(status_code=500, detail="Internal server error")


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
            contents = await file.read()

            # Enforce upload size limit before processing
            max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
            if len(contents) > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum size is {settings.MAX_UPLOAD_SIZE_MB} MB."
                )

            # Run CPU-intensive base64 encoding in a thread
            b64_bytes = await asyncio.to_thread(base64.b64encode, contents)
            b64_encoded = b64_bytes.decode("utf-8")
            mime_type = file.content_type or "application/octet-stream"

            if mime_type.startswith("image/"):
                image_data = {"data": b64_encoded, "mime_type": mime_type}
            else:
                file_data = {"data": b64_encoded, "mime_type": mime_type}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Error reading uploaded file: {e}")

    try:
        reply = await ChatService.process_chat(
            session_id=session_id,
            prompt=prompt,
            model_name=normalized_model,
            db=db,
            user_id=current_user.id,
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
    except Exception:
        logger.exception("Error processing Upload chat")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/stream")
@limiter.limit("5/minute")
async def handle_chat_stream(
    request: Request,
    request_data: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Streaming chat via Server-Sent Events (text/event-stream).
    Each chunk is sent as: data: {"delta": "<text>"}\n\n
    The stream ends with: data: [DONE]\n\n
    """
    normalized_model = _validate_model_name(request_data.model)

    image_data = None
    if request_data.image_base64 and request_data.image_mime_type:
        _validate_base64(request_data.image_base64, "image_base64")
        image_data = {"data": request_data.image_base64, "mime_type": request_data.image_mime_type}

    file_data = None
    if request_data.file_base64 and request_data.file_mime_type:
        _validate_base64(request_data.file_base64, "file_base64")
        file_data = {"data": request_data.file_base64, "mime_type": request_data.file_mime_type}

    async def event_generator():
        try:
            async for chunk in ChatService.process_chat_stream(
                session_id=request_data.session_id,
                prompt=request_data.prompt,
                model_name=normalized_model,
                db=db,
                user_id=current_user.id,
                openai_client=getattr(request.app.state, "openai_client", None),
                image_data=image_data,
                file_data=file_data,
                use_search=request_data.use_search,
            ):
                yield f"data: {json.dumps({'delta': chunk})}\n\n"
        except HTTPException as e:
            yield f"data: {json.dumps({'error': e.detail})}\n\n"
        except Exception:
            logger.exception("Error in stream event generator")
            yield f"data: {json.dumps({'error': 'Internal server error'})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
