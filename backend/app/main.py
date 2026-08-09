from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
import app.database as database
import app.models  # Tablo tanımlarını yükle
from app.routers import inventory, shipments, scan, operation
from app.services.lookup_cache import lookup_cache
from app.ws_manager import ws_manager

import asyncio


@asynccontextmanager
async def lifespan(app: FastAPI):
    # WebSocket broadcast için ana event loop referansını kaydet
    ws_manager.set_event_loop(asyncio.get_running_loop())
    # Veritabanı tabloları yoksa otomatik oluştur
    database.Base.metadata.create_all(bind=database.engine)
    db = database.SessionLocal()
    try:
        lookup_cache.load_all_active(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="SevkiyatBul - FIFO Kontrol Sistemi",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app|https://.*\.onrender\.com|http://localhost:.*|http://127\.0\.0\.1:.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(inventory.router)
app.include_router(shipments.router)
app.include_router(scan.router)
app.include_router(operation.router)


@app.api_route("/", methods=["GET", "HEAD"])
@app.api_route("/ping", methods=["GET", "HEAD"])
@app.api_route("/health", methods=["GET", "HEAD"])
@app.api_route("/healthz", methods=["GET", "HEAD"])
@app.api_route("/api/health", methods=["GET", "HEAD"])
def uptimerobot_health(request: Request):
    """
    UptimeRobot & Uptime Monitoring Endpoint:
    Ücretsiz UptimeRobot istekleri HEAD metodu ile gönderilmektedir.
    Bu fonksiyon hem HEAD hem GET isteklerine HTTP 200 OK yanıtı döner.
    """
    headers = {"X-Uptime-Robot": "OK", "Cache-Control": "no-cache, no-store, must-revalidate"}
    if request.method == "HEAD":
        return Response(status_code=200, headers=headers)

    return JSONResponse(
        content={
            "status": "ok",
            "service": "SevkiyatBul",
            "version": "2.1.0",
            "uptimerobot": "enabled (HEAD & GET supported)",
            "features": [
                "shipment_targets", "global_scan", "operation_flow",
                "shipment_reset", "scan_undo", "scanned_labels", "uptimerobot_head",
                "realtime_ws",
            ],
        },
        headers=headers,
    )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Gerçek zamanlı canlı güncelleme WebSocket endpoint'i."""
    await ws_manager.connect(websocket)
    try:
        while True:
            # İstemciden gelen ping/pong mesajlarını dinle (bağlantıyı canlı tut)
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)
