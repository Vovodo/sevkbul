from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
import app.database as database
from app.routers import inventory, shipments, scan, operation
from app.services.lookup_cache import lookup_cache


@asynccontextmanager
async def lifespan(app: FastAPI):
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
            ],
        },
        headers=headers,
    )
