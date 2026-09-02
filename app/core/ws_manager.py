"""WebSocket Manager — Fase 7.2"""
import asyncio
import logging
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active: Dict[int, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.active.setdefault(user_id, set()).add(websocket)
        logger.info(f"WS connected user={user_id} total={len(self.active[user_id])}")

    def disconnect(self, websocket: WebSocket, user_id: int):
        try:
            self.active.get(user_id, set()).discard(websocket)
            if not self.active.get(user_id):
                self.active.pop(user_id, None)
        except Exception:
            pass
        logger.info(f"WS disconnected user={user_id}")

    async def send_json(self, websocket: WebSocket, data: dict):
        try:
            await websocket.send_json(data)
        except Exception as e:
            logger.warning(f"WS send failed: {e}")

    async def ping_loop(self, websocket: WebSocket, interval: float = 30.0):
        """Periodic ping to keep connection alive."""
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    await websocket.ping()
                except Exception:
                    break
        except asyncio.CancelledError:
            pass


manager = ConnectionManager()
