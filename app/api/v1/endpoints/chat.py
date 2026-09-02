import asyncio
import base64
import json
import logging
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import registry
from app.api import deps
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.models import User
from app.db.session import get_db
from app.schemas.chat import ChatRequest, ChatResponse, ChatUsage
from app.schemas.orchestration import AgentInfo, OrchestrateRequest, OrchestrateResponse
from app.services.chat_service import ChatService
from app.services.token_counter import count_message_tokens, estimate_cost

router = APIRouter()
logger = logging.getLogger(__name__)

# Regex for validating base64 strings (standard + URL-safe alphabets, padding optional)
_B64_RE = re.compile(r'^[A-Za-z0-9+/\-_]*={0,2}$')


def _validate_model_name(model_input: str | None) -> str:
    """
    Normalizes and validates the requested model against allowed configuration.
    Raises HTTP 400 if the model is not in the allowed set.
    """
    default_model = settings.ALLOWED_MODELS_LIST[0] if settings.ALLOWED_MODELS_LIST else "gemini-3.1-pro"
    m = (model_input or default_model).strip().lower()

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

        prompt_tokens = count_message_tokens(request_data.prompt, "user")
        completion_tokens = count_message_tokens(reply, "model")
        total_tokens = prompt_tokens + completion_tokens
        cost_usd = estimate_cost(prompt_tokens, normalized_model) + estimate_cost(
            completion_tokens, normalized_model
        )
        usage = ChatUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
        )
        return ChatResponse(
            session_id=request_data.session_id,
            reply=reply,
            model_used=normalized_model,
            usage=usage,
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
    model: str | None = Form(None),
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

        prompt_tokens = count_message_tokens(prompt, "user")
        completion_tokens = count_message_tokens(reply, "model")
        total_tokens = prompt_tokens + completion_tokens
        cost_usd = estimate_cost(prompt_tokens, normalized_model) + estimate_cost(
            completion_tokens, normalized_model
        )
        usage = ChatUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
        )
        return ChatResponse(
            session_id=session_id,
            reply=reply,
            model_used=normalized_model,
            usage=usage,
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


@router.get("/agents", response_model=list[AgentInfo])
@limiter.limit("30/minute")
async def list_agents(
    request: Request,
    current_user: User = Depends(deps.get_current_user),
):
    return [
        AgentInfo(
            name=c.name,
            description=c.description,
            model=c.model,
            temperature=c.temperature,
            tools=c.tools,
            max_history=c.max_history,
        )
        for c in registry.list_configs()
    ]


@router.post("/orchestrate", response_model=OrchestrateResponse)
@limiter.limit("5/minute")
async def handle_orchestrate(
    request: Request,
    request_data: OrchestrateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    normalized_model = _validate_model_name(request_data.model)
    image_data = None
    if request_data.image_base64 and request_data.image_mime_type:
        _validate_base64(request_data.image_base64, "image_base64")
        image_data = {"data": request_data.image_base64, "mime_type": request_data.image_mime_type}
    file_data = None
    if request_data.file_base64 and request_data.file_mime_type:
        _validate_base64(request_data.file_base64, "file_base64")
        file_data = {"data": request_data.file_base64, "mime_type": request_data.file_mime_type}

    try:
        reply, trace = await ChatService.process_chat_orchestrated(
            session_id=request_data.session_id,
            prompt=request_data.prompt,
            model_name=normalized_model,
            db=db,
            user_id=current_user.id,
            openai_client=getattr(request.app.state, "openai_client", None),
            image_data=image_data,
            file_data=file_data,
            use_search=request_data.use_search,
            strategy=request_data.strategy,
        )
        return OrchestrateResponse(
            session_id=request_data.session_id,
            reply=reply,
            trace=[{"agent": t["agent"], "output": t["output"], "error": t.get("error", False)} for t in trace],
            strategy=request_data.strategy,
            model_used=normalized_model,
        )
    except Exception:
        logger.exception("Error in orchestrate")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/orchestrate/stream")
@limiter.limit("5/minute")
async def handle_orchestrate_stream(
    request: Request,
    request_data: OrchestrateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
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
            async for event in ChatService.process_chat_stream_orchestrated(
                session_id=request_data.session_id,
                prompt=request_data.prompt,
                model_name=normalized_model,
                db=db,
                user_id=current_user.id,
                openai_client=getattr(request.app.state, "openai_client", None),
                image_data=image_data,
                file_data=file_data,
                use_search=request_data.use_search,
                strategy=request_data.strategy,
            ):
                # event is dict {agent, event, delta}
                yield f"event: {event.get('agent','unknown')}\n"
                yield f"data: {json.dumps(event)}\n\n"
        except HTTPException as e:
            yield f"data: {json.dumps({'error': e.detail})}\n\n"
        except Exception:
            logger.exception("Error in orchestrate stream")
            yield f"data: {json.dumps({'error': 'Internal server error'})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
