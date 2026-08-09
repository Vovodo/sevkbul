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
        """Senkron context'ten broadcast başlat (REST endpoint'lerden çağrılır)."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(event, data))
        except RuntimeError:
            pass


# Singleton instance
ws_manager = ConnectionManager()
