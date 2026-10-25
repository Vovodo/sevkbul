from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
import app.database as database
import app.models  # Tablo tanımlarını yükle
from app.routers import inventory, shipments, scan, operation
from app.services.lookup_cache import lookup_cache
from app.services.fifo_quota import backfill_missing_quotas
from app.ws_manager import ws_manager

import asyncio


def _ensure_shipment_sort_order() -> None:
    """Eski veritabanında liste sırası yoksa ekler ve mevcut sevkiyatları korur."""
    from sqlalchemy import inspect, text

    inspector = inspect(database.engine)
    if "shipments" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("shipments")}
    if "sort_order" not in columns:
        with database.engine.begin() as conn:
            conn.execute(text("ALTER TABLE shipments ADD COLUMN sort_order INTEGER"))
    with database.engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id, group_id, created_at FROM shipments "
            "WHERE UPPER(status) IN ('ACTIVE', 'COMPLETED') "
            "ORDER BY created_at ASC, id ASC"
        )).fetchall()
        rank: dict[int, int] = {}
        next_rank = 0
        for row in rows:
            gid = row.group_id if row.group_id is not None else row.id
            if gid not in rank:
                rank[gid] = next_rank
                next_rank += 1
        for row in rows:
            gid = row.group_id if row.group_id is not None else row.id
            conn.execute(
                text("UPDATE shipments SET sort_order = :ord WHERE id = :id AND sort_order IS NULL"),
                {"ord": rank[gid], "id": row.id},
            )


def _ensure_shipment_stock_note() -> None:
    """Eski veritabanında stok uyarı sütunu yoksa ekler."""
    from sqlalchemy import inspect, text

    inspector = inspect(database.engine)
    if "shipments" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("shipments")}
    if "stock_note" in columns:
        return
    with database.engine.begin() as conn:
        conn.execute(text("ALTER TABLE shipments ADD COLUMN stock_note VARCHAR(300)"))


def _ensure_target_source_name() -> None:
    """Eski veritabanında sevkiyat adı sütunu yoksa ekler."""
    from sqlalchemy import inspect, text

    inspector = inspect(database.engine)
    if "shipment_targets" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("shipment_targets")}
    if "source_name" in columns:
        return
    with database.engine.begin() as conn:
        conn.execute(text("ALTER TABLE shipment_targets ADD COLUMN source_name VARCHAR(200)"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # WebSocket broadcast için ana event loop referansını kaydet
    ws_manager.set_event_loop(asyncio.get_running_loop())
    # Veritabanı tabloları yoksa otomatik oluştur
    database.Base.metadata.create_all(bind=database.engine)
    _ensure_target_source_name()
    _ensure_shipment_stock_note()
    _ensure_shipment_sort_order()
    db = database.SessionLocal()
    try:
        backfill_missing_quotas(db)
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
    allow_origins=settings.all_cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app|https://.*\.onrender\.com|https://.*\.rfqcollector\.com|http://localhost:.*|http://127\.0\.0\.1:.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(inventory.router)
app.include_router(shipments.router)
app.include_router(scan.router)
app.include_router(operation.router)

# APK ve statik dosyaları serve et (backend/static/ klasöründen)
import os
from fastapi.staticfiles import StaticFiles

_static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.exists(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


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


@app.get("/api/download/apk")
@app.get("/downloads/SevkiyatBul.apk")
def download_apk():
    """
    Mobil Android APK İndirme Endpoint'i:
    Kullanıcılar web arayüzündeki QR kod veya indirme butonu ile doğrudan APK'yı indirir.
    """
    import os
    from fastapi.responses import FileResponse

    # Statik dizindeki APK dosyasını kontrol et
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    apk_path = os.path.join(base_dir, "static", "SevkiyatBul.apk")

    if os.path.exists(apk_path):
        return FileResponse(
            path=apk_path,
            filename="SevkiyatBul.apk",
            media_type="application/vnd.android.package-archive",
        )

    # APK henüz yüklenmemişse bilgilendirici yanıt dön
    return JSONResponse(
        status_code=200,
        content={
            "status": "info",
            "message": "APK derleme hazırlandı. APK dosyasını 'backend/static/SevkiyatBul.apk' dizinine yükleyebilir veya mobil web arayüzünü doğrudan kullanabilirsiniz.",
            "mobile_web_url": "https://sevkbul.rfqcollector.com",
            "github_repo": "https://github.com/Vovodo/sevkbul",
        },
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
