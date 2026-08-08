from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ScanRequest, ScanResponseSchema, ScanLogSchema
from app.services.scan_service import process_scan
from app.models import ScanLog, InventoryLabel, ScanResult
from app.services.lookup_cache import lookup_cache

router = APIRouter(prefix="/api/scan", tags=["scan"])


@router.post("/{shipment_id}", response_model=ScanResponseSchema)
def scan_label(shipment_id: int, req: ScanRequest, db: Session = Depends(get_db)):
    if not req.label.strip():
        raise HTTPException(status_code=400, detail="Etiket boş olamaz")

    try:
        result = process_scan(db, shipment_id, req.label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ScanResponseSchema(
        result=result.result,
        label=result.label,
        reference=result.reference,
        quantity=result.quantity,
        scanned_quantity=result.scanned_quantity,
        remaining_quantity=result.remaining_quantity,
        progress_percent=result.progress_percent,
        is_complete=result.is_complete,
    )


@router.post("/{shipment_id}/lookup", response_model=ScanResponseSchema)
def fast_lookup(shipment_id: int, req: ScanRequest, db: Session = Depends(get_db)):
    """Fast in-memory lookup endpoint - same as scan but optimized path."""
    return scan_label(shipment_id, req, db)


@router.get("/{shipment_id}/history", response_model=list[ScanLogSchema])
def scan_history(shipment_id: int, limit: int = 100, db: Session = Depends(get_db)):
    logs = (
        db.query(ScanLog)
        .filter(ScanLog.shipment_id == shipment_id)
        .order_by(ScanLog.scanned_at.desc())
        .limit(limit)
        .all()
    )

    result = []
    for log in logs:
        ref = None
        qty = None
        if log.inventory_label_id:
            inv = db.query(InventoryLabel).filter(InventoryLabel.id == log.inventory_label_id).first()
            if inv:
                ref = inv.reference
                qty = float(inv.quantity)

        result.append(ScanLogSchema(
            id=log.id,
            scanned_value=log.scanned_value,
            reference=ref,
            quantity=qty,
            result=log.result.value,
            scanned_at=log.scanned_at,
        ))
    return result


@router.get("/history/all", response_model=list[ScanLogSchema])
def all_scan_history(limit: int = 200, db: Session = Depends(get_db)):
    logs = (
        db.query(ScanLog)
        .order_by(ScanLog.scanned_at.desc())
        .limit(limit)
        .all()
    )

    result = []
    for log in logs:
        ref = None
        qty = None
        if log.inventory_label_id:
            inv = db.query(InventoryLabel).filter(InventoryLabel.id == log.inventory_label_id).first()
            if inv:
                ref = inv.reference
                qty = float(inv.quantity)

        result.append(ScanLogSchema(
            id=log.id,
            scanned_value=log.scanned_value,
            reference=ref,
            quantity=qty,
            result=log.result.value,
            scanned_at=log.scanned_at,
        ))
    return result
