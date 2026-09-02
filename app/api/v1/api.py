from fastapi import APIRouter
from app.api.v1.endpoints import auth, chat, conversations, documents, ws, files

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(files.router, prefix="/files", tags=["files"])
# WS router is mounted separately in main for /ws prefix handling, but also include here for docs
api_router.include_router(ws.router, tags=["ws"])