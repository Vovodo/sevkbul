from contextlib import asynccontextmanager

from fastapi import FastAPI
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
    version="1.0.0",
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


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "service": "SevkiyatBul",
        "version": "2.1",
        "features": [
            "shipment_targets", "global_scan", "operation_flow",
            "shipment_reset", "scan_undo", "scanned_labels",
        ],
    }
