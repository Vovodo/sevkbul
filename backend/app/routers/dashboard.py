from datetime import datetime, date
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.schemas import DashboardSchema
from app.models import Shipment, ShipmentStatus, ScanLog, ScanResult

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/", response_model=DashboardSchema)
def get_dashboard(db: Session = Depends(get_db)):
    active = db.query(func.count(Shipment.id)).filter(
        Shipment.status == ShipmentStatus.ACTIVE
    ).scalar() or 0

    today_start = datetime.combine(date.today(), datetime.min.time())
    today = db.query(func.count(Shipment.id)).filter(
        Shipment.created_at >= today_start
    ).scalar() or 0

    completed = db.query(func.count(Shipment.id)).filter(
        Shipment.status == ShipmentStatus.COMPLETED
    ).scalar() or 0

    in_progress = active

    total_scans = db.query(func.count(ScanLog.id)).scalar() or 0

    error_scans = db.query(func.count(ScanLog.id)).filter(
        ScanLog.result.in_([
            ScanResult.OUTSIDE_SHIPMENT,
            ScanResult.NOT_FOUND,
            ScanResult.ALREADY_SCANNED,
        ])
    ).scalar() or 0

    return DashboardSchema(
        active_shipments=active,
        today_shipments=today,
        completed_shipments=completed,
        in_progress_shipments=in_progress,
        total_scans=total_scans,
        error_scans=error_scans,
    )
