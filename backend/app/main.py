from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
import app.database as database
import app.models  # Tablo tanımlarını yükle
from app.routers import inventory, shipments, scan, operation, sessions
from app.services.lookup_cache import lookup_cache
from app.services.fifo_quota import backfill_missing_quotas
from app.session_context import set_current_session_id, reset_current_session_id, DEFAULT_SESSION_ID
from app.ws_manager import ws_manager

import asyncio
import json


def _ensure_inventory_blocked() -> None:
    """Eski veritabanında blokaj ve gizlilik sütunu yoksa ekler."""
    from sqlalchemy import inspect, text

    inspector = inspect(database.engine)
    if "inventory_labels" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("inventory_labels")}
    if "blocked" not in columns:
        with database.engine.begin() as conn:
            conn.execute(text("ALTER TABLE inventory_labels ADD COLUMN blocked BOOLEAN NOT NULL DEFAULT FALSE"))
    if "hidden" not in columns:
        with database.engine.begin() as conn:
            conn.execute(text("ALTER TABLE inventory_labels ADD COLUMN hidden BOOLEAN NOT NULL DEFAULT FALSE"))


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
            "WHERE UPPER(CAST(status AS VARCHAR)) IN ('ACTIVE', 'COMPLETED') "
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


def _purge_cancelled_shipments() -> None:
    """Eskiden CANCELLED olarak kalmış sevkiyat ve etiket kayıtlarını temizler."""
    from sqlalchemy import inspect, text

    inspector = inspect(database.engine)
    if "shipments" not in inspector.get_table_names():
        return
    with database.engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM shipment_date_quotas WHERE shipment_id IN "
            "(SELECT id FROM shipments WHERE UPPER(CAST(status AS VARCHAR)) = 'CANCELLED')"
        ))
        conn.execute(text(
            "DELETE FROM shipment_labels WHERE shipment_id IN "
            "(SELECT id FROM shipments WHERE UPPER(CAST(status AS VARCHAR)) = 'CANCELLED')"
        ))
        conn.execute(text(
            "DELETE FROM scan_logs WHERE shipment_id IN "
            "(SELECT id FROM shipments WHERE UPPER(CAST(status AS VARCHAR)) = 'CANCELLED')"
        ))
        conn.execute(text("DELETE FROM shipments WHERE UPPER(CAST(status AS VARCHAR)) = 'CANCELLED'"))


def _ensure_multi_session_columns() -> None:
    """
    Mevcut tablolara 'session_id' sütununu ve oturum bazlı indeksleri ekler.
    PostgreSQL'de eski tekil 'ix_inventory_labels_label' kısıtını kaldırıp
    (session_id, label) birleşik tekil indeksine dönüştürür.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(database.engine)
    existing_tables = set(inspector.get_table_names())
    target_tables = (
        "inventory_labels",
        "shipments",
        "scan_logs",
        "shipment_targets",
        "excel_header_settings",
    )
    for tbl in target_tables:
        if tbl not in existing_tables:
            continue
        cols = {c["name"] for c in inspector.get_columns(tbl)}
        if "session_id" not in cols:
            with database.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN session_id INTEGER NOT NULL DEFAULT 1"))
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{tbl}_session_id ON {tbl} (session_id)"))

    # PostgreSQL üzerinde eski tekil 'ix_inventory_labels_label' indeksini (session_id, label) yapısına geçir
    if "inventory_labels" in existing_tables and not str(database.engine.url).startswith("sqlite"):
        try:
            with database.engine.begin() as conn:
                conn.execute(text("ALTER TABLE inventory_labels DROP CONSTRAINT IF EXISTS inventory_labels_label_key"))
                # Eğer ix_inventory_labels_label unique ise yeniden non-unique oluştur
                idx_rows = conn.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE tablename = 'inventory_labels' AND indexname = 'ix_inventory_labels_label'"
                    )
                ).fetchall()
                if idx_rows and "UNIQUE" in (idx_rows[0][0] or "").upper():
                    conn.execute(text("DROP INDEX IF EXISTS ix_inventory_labels_label"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_inventory_labels_label ON inventory_labels (label)"))
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_session_inventory_label "
                        "ON inventory_labels (session_id, label)"
                    )
                )
        except Exception as exc:
            print(f"[DB] uq_session_inventory_label indeks güncelleme bilgisi: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # WebSocket broadcast için ana event loop referansını kaydet
    ws_manager.set_event_loop(asyncio.get_running_loop())
    # Veritabanı tabloları yoksa otomatik oluştur (hata olsa bile sunucu 503 vermesin)
    try:
        database.Base.metadata.create_all(bind=database.engine)
        _ensure_multi_session_columns()
        _ensure_target_source_name()
        _ensure_shipment_stock_note()
        _ensure_shipment_sort_order()
        _ensure_inventory_blocked()
        _purge_cancelled_shipments()
        db = database.SessionLocal()
        try:
            from app.routers.sessions import ensure_default_work_session
            from app.services.s3_storage import hydrate_storage_on_startup
            ensure_default_work_session(db)
            hydrate_storage_on_startup(db)
            backfill_missing_quotas(db)
            lookup_cache.load_all_active(db)
        finally:
            db.close()
    except Exception as exc:
        print(f"[STARTUP ERROR] Veritabanı başlangıç hazırlığında hata oluştu: {exc}")
    yield
    for ws in list(ws_manager.active_connections):
        try:
            await ws.close()
        except Exception:
            pass
    ws_manager.active_connections.clear()


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

app.include_router(sessions.router)
app.include_router(inventory.router)
app.include_router(shipments.router)
app.include_router(scan.router)
app.include_router(operation.router)


@app.middleware("http")
async def session_context_middleware(request: Request, call_next):
    """
    Her HTTP isteğinde X-Session-Id başlığını veya ?session_id= sorgu parametresini
    okur ve aktif çalışma oturumu bağlamını (ContextVar) ayarlar.
    Belirtilmemişse varsayılan oturum (1) kullanılır.
    """
    raw_sid = request.headers.get("X-Session-Id") or request.query_params.get("session_id")
    sid = DEFAULT_SESSION_ID
    if raw_sid:
        try:
            parsed = int(raw_sid)
            if parsed > 0:
                sid = parsed
        except (ValueError, TypeError):
            sid = DEFAULT_SESSION_ID

    token = set_current_session_id(sid)
    try:
        return await call_next(request)
    finally:
        reset_current_session_id(token)

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



def _broadcast_sessions_snapshot() -> None:
    """Tüm bağlı ekranlara güncel oturum listesini ve bağlı cihaz sayılarını yayınlar."""
    try:
        from app.routers.sessions import list_work_sessions_with_stats
        db = database.SessionLocal()
        try:
            items = [s.model_dump() for s in list_work_sessions_with_stats(db)]
            ws_manager.broadcast_sync("sessions_updated", items, all_rooms=True)
        finally:
            db.close()
    except Exception:
        pass


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Oturum (session_id) odasına duyarlı gerçek zamanlı canlı güncelleme WebSocket endpoint'i."""
    raw_sid = websocket.query_params.get("session_id")
    sid = DEFAULT_SESSION_ID
    if raw_sid:
        try:
            parsed = int(raw_sid)
            if parsed > 0:
                sid = parsed
        except (ValueError, TypeError):
            sid = DEFAULT_SESSION_ID

    await ws_manager.connect(websocket, session_id=sid)
    _broadcast_sessions_snapshot()
    try:
        while True:
            msg_text = await websocket.receive_text()
            try:
                payload = json.loads(msg_text)
                if isinstance(payload, dict) and payload.get("action") == "switch_session":
                    new_sid = int(payload.get("session_id") or DEFAULT_SESSION_ID)
                    ws_manager.switch_room(websocket, new_sid)
                    _broadcast_sessions_snapshot()
            except Exception:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        _broadcast_sessions_snapshot()
    except Exception:
        ws_manager.disconnect(websocket)
        _broadcast_sessions_snapshot()
