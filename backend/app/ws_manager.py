"""
WebSocket Bağlantı Yöneticisi — Oturum (Room) Bazlı Gerçek Zamanlı Yayın

Her çalışma oturumu (session_id) kendi bağımsız WebSocket odasına sahiptir:
- X Projesi (session_id=1) içindeki okutma, stok ve sevkiyat olayları yalnızca
  session_id=1 odasına bağlı cihazlara (bilgisayar/el terminali) gider.
- Oturum listesi değiştiğinde ('sessions_updated') tüm bağlı cihazlar bilgilendirilir.
"""
import json
import asyncio
from collections import defaultdict
from typing import Any
from fastapi import WebSocket

from app.session_context import get_current_session_id, DEFAULT_SESSION_ID


class ConnectionManager:
    """Oturum (session_id) odalarına göre izole WebSocket yöneticisi."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self.rooms: dict[int, list[WebSocket]] = defaultdict(list)
        self._ws_session_map: dict[WebSocket, int] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Ana asyncio event loop referansını kaydet (lifespan'dan çağrılır)."""
        self._loop = loop

    async def connect(self, websocket: WebSocket, session_id: int = DEFAULT_SESSION_ID) -> None:
        sid = int(session_id) if session_id and int(session_id) > 0 else DEFAULT_SESSION_ID
        await websocket.accept()
        if websocket not in self.active_connections:
            self.active_connections.append(websocket)
        if websocket not in self.rooms[sid]:
            self.rooms[sid].append(websocket)
        self._ws_session_map[websocket] = sid

    def disconnect(self, websocket: WebSocket) -> int | None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        sid = self._ws_session_map.pop(websocket, None)
        if sid is not None and websocket in self.rooms.get(sid, []):
            self.rooms[sid].remove(websocket)
        for r_list in self.rooms.values():
            if websocket in r_list:
                r_list.remove(websocket)
        return sid

    def switch_room(self, websocket: WebSocket, new_session_id: int) -> None:
        sid = int(new_session_id) if new_session_id and int(new_session_id) > 0 else DEFAULT_SESSION_ID
        old_sid = self._ws_session_map.get(websocket)
        if old_sid is not None and websocket in self.rooms.get(old_sid, []):
            self.rooms[old_sid].remove(websocket)
        if websocket not in self.rooms[sid]:
            self.rooms[sid].append(websocket)
        self._ws_session_map[websocket] = sid

    def room_count(self, session_id: int) -> int:
        return len(self.rooms.get(int(session_id), []))

    async def broadcast(
        self,
        event: str,
        data: Any = None,
        session_id: int | None = None,
        all_rooms: bool = False,
    ) -> None:
        """Belirtilen oturum odasındaki (veya all_rooms=True ise tüm) istemcilere JSON mesajı gönder."""
        sid = int(session_id) if session_id and int(session_id) > 0 else DEFAULT_SESSION_ID
        message = json.dumps({"event": event, "session_id": sid, "data": data}, default=str)
        targets = list(self.active_connections) if all_rooms else list(self.rooms.get(sid, []))
        disconnected: list[WebSocket] = []
        for connection in targets:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

    def broadcast_sync(
        self,
        event: str,
        data: Any = None,
        session_id: int | None = None,
        all_rooms: bool = False,
    ) -> None:
        """
        Senkron context'ten broadcast başlat (REST endpoint'lerden çağrılır).
        Çağrıldığı thread'deki aktif session_id'yi yakalar ve sadece o odaya yayın yapar.
        """
        if self._loop is None or self._loop.is_closed():
            return
        sid = int(session_id) if session_id is not None else get_current_session_id()
        asyncio.run_coroutine_threadsafe(
            self.broadcast(event, data, session_id=sid, all_rooms=all_rooms),
            self._loop,
        )


# Singleton instance
ws_manager = ConnectionManager()
