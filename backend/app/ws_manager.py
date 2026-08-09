"""
WebSocket Bağlantı Yöneticisi - Gerçek Zamanlı Canlı Güncelleme

Tüm bağlı istemcilere okutma, undo ve reset olaylarını anlık olarak yayınlar.
"""
import json
import asyncio
from typing import Any
from fastapi import WebSocket


class ConnectionManager:
    """Tüm aktif WebSocket bağlantılarını yöneten sınıf."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Ana asyncio event loop referansını kaydet (lifespan'dan çağrılır)."""
        self._loop = loop

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, event: str, data: Any = None) -> None:
        """Tüm bağlı istemcilere JSON mesajı gönder."""
        message = json.dumps({"event": event, "data": data}, default=str)
        disconnected: list[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

    def broadcast_sync(self, event: str, data: Any = None) -> None:
        """
        Senkron context'ten broadcast başlat (REST endpoint'lerden çağrılır).

        FastAPI sync endpoint'leri thread pool'da çalışır — bu thread'de
        asyncio event loop yoktur. asyncio.run_coroutine_threadsafe() ile
        ana event loop'a güvenle görev planlıyoruz.
        """
        if self._loop is None or self._loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(event, data), self._loop)


# Singleton instance
ws_manager = ConnectionManager()
