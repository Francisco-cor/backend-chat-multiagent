import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import jwt
from app.core.config import settings
from app.db.session import get_db
from app.db.models import User
from app.core.ws_manager import manager
from app.services.chat_service import ChatService
from app.schemas.chat import ChatRequest

router = APIRouter()
logger = logging.getLogger(__name__)


async def _get_user_from_token(token: str, db: AsyncSession) -> User | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        sub = payload.get("sub")
        if not sub:
            return None
        user_id = int(sub)
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        return user
    except Exception as e:
        logger.warning(f"WS auth failed: {e}")
        return None


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket, token: str = Query(None)):
    # Need db session manually (no Depends works differently with WS, create one)
    from app.db.session import AsyncSessionLocal

    # Validate token presence
    if not token:
        await websocket.close(code=4401, reason="Missing token")
        return

    async with AsyncSessionLocal() as db:
        user = await _get_user_from_token(token, db)
        if not user:
            await websocket.close(code=4401, reason="Invalid token")
            return
        await manager.connect(websocket, user.id)
        # Start ping loop
        ping_task = asyncio.create_task(manager.ping_loop(websocket, interval=settings.WS_PING_INTERVAL))
        try:
            # Send hello
            await websocket.send_json({"type": "hello", "user_id": user.id, "message": "connected"})
            while True:
                try:
                    raw = await websocket.receive_text()
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.warning(f"WS receive error: {e}")
                    break

                # Heartbeat pong handling
                if raw == "ping":
                    await websocket.send_text("pong")
                    continue
                # Parse JSON
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_json({"type": "error", "detail": "invalid json, expected {prompt, session_id, model}"})
                    continue

                prompt = data.get("prompt") or data.get("message")
                session_id = data.get("session_id") or data.get("sessionId") or "ws-default"
                model = data.get("model")
                use_search = data.get("use_search", False)
                image_data = None
                if data.get("image_base64"):
                    image_data = {"data": data["image_base64"], "mime_type": data.get("image_mime_type", "image/png")}
                file_data = None
                if data.get("file_base64"):
                    file_data = {"data": data["file_base64"], "mime_type": data.get("file_mime_type", "text/plain")}
                # Audio handling
                if data.get("audio_base64"):
                    from app.services.transcription_service import transcribe_audio

                    transcript = await transcribe_audio(
                        data["audio_base64"], data.get("audio_mime_type", "audio/webm"), client=getattr(websocket.app.state, "openai_client", None) if hasattr(websocket, "app") else None
                    )
                    prompt = f"{transcript}\n\n{prompt}" if prompt else transcript

                if not prompt:
                    await websocket.send_json({"type": "error", "detail": "prompt required"})
                    continue

                # Validate model
                from app.api.v1.endpoints.chat import _validate_model_name

                try:
                    normalized_model = _validate_model_name(model)
                except Exception as e:
                    await websocket.send_json({"type": "error", "detail": str(e)})
                    continue

                # Ack received
                msg_id = data.get("id") or data.get("msg_id") or ""
                await websocket.send_json({"type": "ack", "id": msg_id, "session_id": session_id})

                # Stream response chunks
                seq = 0
                try:
                    # Need fresh db session for chat service (use the same db but keep session alive)
                    # We reuse the db from outer scope but need to ensure it's alive
                    # Create new session per message for isolation
                    async with AsyncSessionLocal() as msg_db:
                        async for chunk in ChatService.process_chat_stream(
                            session_id=session_id,
                            prompt=prompt,
                            model_name=normalized_model,
                            db=msg_db,
                            user_id=user.id,
                            openai_client=getattr(websocket.app.state, "openai_client", None) if hasattr(websocket.app, "state") else None,
                            image_data=image_data,
                            file_data=file_data,
                            use_search=use_search,
                        ):
                            seq += 1
                            await websocket.send_json({"type": "delta", "delta": chunk, "id": seq, "session_id": session_id})
                    await websocket.send_json({"type": "done", "session_id": session_id, "id": seq})
                except Exception as e:
                    logger.exception(f"WS chat processing error: {e}")
                    await websocket.send_json({"type": "error", "detail": "Internal server error", "session_id": session_id})

        finally:
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass
            manager.disconnect(websocket, user.id)
