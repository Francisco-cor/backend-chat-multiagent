import asyncio
import base64
import json
import logging
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import registry
from app.api import deps
from app.core.config import settings
from app.core.rate_limit import limiter, redis_sliding_window
from app.db.models import User
from app.db.session import get_db
from app.schemas.chat import ChatRequest, ChatResponse, ChatUsage
from app.schemas.orchestration import AgentInfo, OrchestrateRequest, OrchestrateResponse
from app.services.chat_service import ChatService
from app.services.token_counter import count_message_tokens, estimate_cost
from app.services import quota_service as quota_svc
from app.services.billing_service import record_usage

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


def _check_chat_write_scope(request: Request):
    """Enforce chat:write scope for API keys (JWT bypass)."""
    principal_type = getattr(request.state, "principal_type", None)
    if principal_type == "api_key":
        scopes = getattr(request.state, "api_key_scopes", []) or []
        if "chat:write" not in scopes:
            raise HTTPException(status_code=403, detail="Missing scope: chat:write")


async def _enforce_redis_rate(request: Request, current_user: User):
    """Per-principal sliding window via Redis (distributed) fallback to memory."""
    key = getattr(request.state, "principal_id", None) or f"user:{current_user.id}"
    # chat limit 5/min matches slowapi but distributed
    allowed, remaining = await redis_sliding_window.is_allowed(f"chat:{key}", limit=5, window_seconds=60)
    if not allowed:
        from fastapi import HTTPException as HE

        raise HE(
            status_code=429,
            detail="Rate limit exceeded (redis)",
            headers={"Retry-After": "60", "X-RateLimit-Remaining": str(remaining)},
        )
    # stash for headers
    request.state.rl_remaining = remaining


async def _enforce_quota_check(request: Request, db: AsyncSession, current_user: User, prompt: str, response=None):
    """Quota soft/hard + headers."""
    prompt_tokens = count_message_tokens(prompt, "user")
    info = await quota_svc.check_quota(db, current_user, tokens_needed=prompt_tokens)
    if info["hard_hit"]:
        raise HTTPException(
            status_code=429,
            detail={"error": "Quota exceeded", "plan": getattr(current_user, "plan", "free"), "limit": info["limit"], "used": info["used"]},
            headers={"Retry-After": "3600", "X-Quota-Remaining": str(info["remaining"]), "X-Quota-Limit": str(info["limit"])},
        )
    # headers
    if response is not None:
        response.headers["X-Quota-Remaining"] = str(info["remaining"])
        response.headers["X-Quota-Limit"] = str(info["limit"])
        response.headers["X-Quota-Used"] = str(info["used"])
        if info["soft_hit"]:
            response.headers["X-Quota-Warning"] = "soft-limit"
    else:
        # stash on request for streaming
        request.state.quota_remaining = str(info["remaining"])
        request.state.quota_limit = str(info["limit"])
    return info


async def _record_ledger(db: AsyncSession, request: Request, current_user: User, model: str, prompt: str, reply: str):
    try:
        prompt_tokens = count_message_tokens(prompt, "user")
        completion_tokens = count_message_tokens(reply, "model")
        cost = estimate_cost(prompt_tokens, model) + estimate_cost(completion_tokens, model)
        api_key_id = getattr(request.state, "api_key_id", None) or getattr(getattr(request.state, "api_key", None), "id", None)
        request_id = request.headers.get("x-request-id") or request.headers.get("X-Request-ID")
        endpoint = request.url.path
        await record_usage(
            db,
            user_id=current_user.id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            api_key_id=api_key_id,
            request_id=request_id,
            endpoint=endpoint,
        )
    except Exception as e:
        logger.warning(f"Ledger record failed: {e}")


@router.post("/", response_model=ChatResponse)
@limiter.limit("5/minute")
async def handle_chat_json(
    request: Request,
    response: Response,
    request_data: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Main endpoint for chat via JSON.
    Supports: Text, Images (base64), Files (base64), and Grounding (use_search).
    Rate/Quota: redis sliding-window + monthly quota + billing ledger.
    """
    _check_chat_write_scope(request)
    await _enforce_redis_rate(request, current_user)
    await _enforce_quota_check(request, db, current_user, request_data.prompt, response=response)
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
        # billing ledger (async, best-effort)
        await _record_ledger(db, request, current_user, normalized_model, request_data.prompt, reply)
        # propagate rate-limit remaining header
        if hasattr(request.state, "rl_remaining"):
            response.headers["X-RateLimit-Remaining"] = str(request.state.rl_remaining)
        return ChatResponse(
            session_id=request_data.session_id,
            reply=reply,
            model_used=normalized_model,
            usage=usage,
        )

    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error processing JSON chat")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/upload", response_model=ChatResponse)
@limiter.limit("5/minute")
async def handle_chat_with_upload(
    request: Request,
    response: Response,
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
    _check_chat_write_scope(request)
    await _enforce_redis_rate(request, current_user)
    await _enforce_quota_check(request, db, current_user, prompt, response=response)
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
        await _record_ledger(db, request, current_user, normalized_model, prompt, reply)
        if hasattr(request.state, "rl_remaining"):
            response.headers["X-RateLimit-Remaining"] = str(request.state.rl_remaining)
        return ChatResponse(
            session_id=session_id,
            reply=reply,
            model_used=normalized_model,
            usage=usage,
        )

    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except HTTPException:
        raise
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
    Streaming chat via Server-Sent Events (text/event-stream) — resilient.

    Features (Fase 7.1):
     - monotonic id per chunk
     - retry: 3000 hint
     - heartbeat : heartbeat every 15s
     - Last-Event-ID resume from in-memory buffer
     - backpressure via bounded queue
    Each chunk is sent as: id: <n>\\ndata: {"delta": "<text>", "id": <n>}\\n\\n
    The stream ends with: data: [DONE]\\n\\n
    """
    _check_chat_write_scope(request)
    await _enforce_redis_rate(request, current_user)
    # quota check will be done after audio transcription (need final prompt)
    normalized_model = _validate_model_name(request_data.model)

    image_data = None
    if request_data.image_base64 and request_data.image_mime_type:
        _validate_base64(request_data.image_base64, "image_base64")
        image_data = {"data": request_data.image_base64, "mime_type": request_data.image_mime_type}

    file_data = None
    if request_data.file_base64 and request_data.file_mime_type:
        _validate_base64(request_data.file_base64, "file_base64")
        file_data = {"data": request_data.file_base64, "mime_type": request_data.file_mime_type}

    # Audio transcription — if audio provided, prepend transcript to prompt
    prompt = request_data.prompt
    if request_data.audio_base64:
        _validate_base64(request_data.audio_base64, "audio_base64")
        from app.services.transcription_service import transcribe_audio

        transcript = await transcribe_audio(
            request_data.audio_base64,
            request_data.audio_mime_type or "audio/webm",
            client=getattr(request.app.state, "openai_client", None),
        )
        # If transcript dummy, just append; if real, replace prompt with transcript + prompt
        prompt = f"{transcript}\n\n{prompt}" if prompt else transcript

    await _enforce_quota_check(request, db, current_user, prompt)

    # Parse Last-Event-ID for resume
    last_event_id_raw = request.headers.get("last-event-id") or request.headers.get("Last-Event-ID")
    try:
        last_event_id = int(last_event_id_raw) if last_event_id_raw else 0
    except ValueError:
        last_event_id = 0

    full_reply_parts: list[str] = []

    async def inner_gen():
        async for chunk in ChatService.process_chat_stream(
            session_id=request_data.session_id,
            prompt=prompt,
            model_name=normalized_model,
            db=db,
            user_id=current_user.id,
            openai_client=getattr(request.app.state, "openai_client", None),
            image_data=image_data,
            file_data=file_data,
            use_search=request_data.use_search,
        ):
            full_reply_parts.append(chunk)
            yield chunk

    from app.services.stream_manager import resilient_stream

    async def event_generator():
        try:
            async for frame in resilient_stream(
                request_data.session_id,
                inner_gen(),
                last_event_id=last_event_id,
                heartbeat_interval=settings.SSE_HEARTBEAT_SECONDS,
            ):
                yield frame
                # SSE spec: also yield heartbeat already inside manager
            # billing after stream
            if full_reply_parts:
                await _record_ledger(db, request, current_user, normalized_model, prompt, "".join(full_reply_parts))
            yield "data: [DONE]\n\n"
        except HTTPException as e:
            yield f"data: {json.dumps({'error': e.detail})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception:
            logger.exception("Error in stream event generator")
            yield f"data: {json.dumps({'error': 'Internal server error'})}\n\n"
            yield "data: [DONE]\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "X-Quota-Remaining": getattr(request.state, "quota_remaining", ""),
        "X-Quota-Limit": getattr(request.state, "quota_limit", ""),
    }
    # clean empty
    headers = {k: v for k, v in headers.items() if v}
    if hasattr(request.state, "rl_remaining"):
        headers["X-RateLimit-Remaining"] = str(request.state.rl_remaining)
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


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
    response: Response,
    request_data: OrchestrateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    _check_chat_write_scope(request)
    await _enforce_redis_rate(request, current_user)
    await _enforce_quota_check(request, db, current_user, request_data.prompt, response=response)
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
        await _record_ledger(db, request, current_user, normalized_model, request_data.prompt, reply)
        if hasattr(request.state, "rl_remaining"):
            response.headers["X-RateLimit-Remaining"] = str(request.state.rl_remaining)
        return OrchestrateResponse(
            session_id=request_data.session_id,
            reply=reply,
            trace=[{"agent": t["agent"], "output": t["output"], "error": t.get("error", False)} for t in trace],
            strategy=request_data.strategy,
            model_used=normalized_model,
        )
    except HTTPException:
        raise
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
    _check_chat_write_scope(request)
    await _enforce_redis_rate(request, current_user)
    await _enforce_quota_check(request, db, current_user, request_data.prompt)
    normalized_model = _validate_model_name(request_data.model)
    image_data = None
    if request_data.image_base64 and request_data.image_mime_type:
        _validate_base64(request_data.image_base64, "image_base64")
        image_data = {"data": request_data.image_base64, "mime_type": request_data.image_mime_type}
    file_data = None
    if request_data.file_base64 and request_data.file_mime_type:
        _validate_base64(request_data.file_base64, "file_base64")
        file_data = {"data": request_data.file_base64, "mime_type": request_data.file_mime_type}

    # Parse Last-Event-ID for orchestrate stream too
    last_event_id_raw = request.headers.get("last-event-id") or request.headers.get("Last-Event-ID")
    try:
        last_event_id = int(last_event_id_raw) if last_event_id_raw else 0
    except ValueError:
        last_event_id = 0

    async def inner_event_gen():
        seq = 0
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
            seq += 1
            # emit as JSON delta per agent
            yield event

    # We wrap with resilient framing but keep agent event type
    from app.services.stream_manager import get_buffered
    import asyncio as _asyncio

    async def event_generator():
        # replay if needed (from in-memory buffer of orchestrate? reuse same buffer key prefixed)
        buffer_key = f"orch:{request_data.session_id}"
        if last_event_id:
            from app.services.stream_manager import get_buffered as _get_buf

            replay = _get_buf(buffer_key, last_event_id)
            for eid, delta_json in replay:
                yield f"id: {eid}\ndata: {delta_json}\n\n"
        yield "retry: 3000\n\n"
        queue: _asyncio.Queue = _asyncio.Queue(maxsize=20)
        done = _asyncio.Event()

        async def producer():
            try:
                async for ev in inner_event_gen():
                    await queue.put(ev)
            except Exception as e:
                logger.warning(f"Orch stream producer error: {e}")
                await queue.put(e)  # type: ignore
            finally:
                done.set()
                await queue.put(None)

        prod = _asyncio.create_task(producer())
        _counter = last_event_id or 0
        full_deltas: list[str] = []
        try:
            while True:
                try:
                    item = await _asyncio.wait_for(queue.get(), timeout=settings.SSE_HEARTBEAT_SECONDS)
                except _asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if item is None:
                    break
                if isinstance(item, Exception):
                    yield f"data: {json.dumps({'error': str(item)})}\n\n"
                    break
                _counter += 1
                # store for resume
                from app.services.stream_manager import _buffers, _counters

                _counters[buffer_key] = _counter
                # keep buffer
                import json as _json

                payload = _json.dumps(item)
                _buffers[buffer_key].append((_counter, payload))
                # collect for billing
                delta = item.get("delta") if isinstance(item, dict) else None
                if delta:
                    full_deltas.append(delta)
                # SSE with event type = agent
                agent = item.get("agent", "unknown")
                yield f"id: {_counter}\nevent: {agent}\ndata: {payload}\n\n"
        finally:
            prod.cancel()
            try:
                await prod
            except _asyncio.CancelledError:
                pass
            if full_deltas:
                try:
                    await _record_ledger(db, request, current_user, normalized_model, request_data.prompt, "".join(full_deltas))
                except Exception:
                    pass
            yield "data: [DONE]\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "X-Quota-Remaining": getattr(request.state, "quota_remaining", ""),
        "X-Quota-Limit": getattr(request.state, "quota_limit", ""),
    }
    headers = {k: v for k, v in headers.items() if v}
    if hasattr(request.state, "rl_remaining"):
        headers["X-RateLimit-Remaining"] = str(request.state.rl_remaining)
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)
