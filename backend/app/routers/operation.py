from decimal import Decimal

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    ShipmentTargetSchema, ShipmentTargetCreateSchema,
    ShipmentFindResultSchema, ShipmentProgressSchema,
    ScanRequest, ScanResponseSchema, ScanLogSchema,
    ShipmentTargetImportResultSchema, RowErrorSchema, ScannedLabelSchema,
)
from app.services.target_service import list_targets, add_target, clear_targets, find_shipments
from app.services.shipment_excel_import import import_shipment_targets_excel
from app.services.shipment_service import get_active_shipments, get_shipment_progress
from app.services.scan_service import process_global_scan
from app.services.operation_service import reset_active_shipments, get_scanned_labels, undo_scan
from app.models import ScanLog, InventoryLabel

router = APIRouter(prefix="/api/shipment", tags=["shipment"])


@router.get("/targets", response_model=list[ShipmentTargetSchema])
def get_targets(db: Session = Depends(get_db)):
    return [ShipmentTargetSchema(id=t.id, reference=t.reference, target_quantity=t.target_quantity) for t in list_targets(db)]


@router.post("/targets", response_model=ShipmentTargetSchema)
def create_target(req: ShipmentTargetCreateSchema, db: Session = Depends(get_db)):
    try:
        t = add_target(db, req.reference, req.target_quantity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ShipmentTargetSchema(id=t.id, reference=t.reference, target_quantity=t.target_quantity)


@router.delete("/targets")
def delete_targets(db: Session = Depends(get_db)):
    clear_targets(db)
    return {"ok": True}


@router.post("/targets/import", response_model=ShipmentTargetImportResultSchema)
async def import_targets_excel(
    file: UploadFile = File(...),
    replace: bool = True,
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Geçersiz dosya formatı")
    try:
        content = await file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Excel okunamadı")

    result = import_shipment_targets_excel(db, content, replace=replace)
    if result.missing_columns:
        raise HTTPException(status_code=400, detail=f"Eksik kolonlar: {', '.join(result.missing_columns)}")

    return ShipmentTargetImportResultSchema(
        total_rows=result.total_rows,
        successful=result.successful,
        error_count=len(result.errors),
        errors=[RowErrorSchema(row=e.row, reason=e.reason) for e in result.errors[:50]],
        missing_columns=result.missing_columns,
        targets=[ShipmentTargetSchema(**t) for t in result.targets],
    )


@router.post("/find", response_model=ShipmentFindResultSchema)
def find_shipment_pools(db: Session = Depends(get_db)):
    try:
        result = find_shipments(db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    shipments = []
    for s in result["shipments"]:
        prog = get_shipment_progress(db, s["shipment_id"])
        shipments.append(ShipmentProgressSchema(**prog))

    return ShipmentFindResultSchema(shipments=shipments, errors=result["errors"])


@router.post("/reset")
def reset_shipments(db: Session = Depends(get_db)):
    count = reset_active_shipments(db)
    return {"cancelled": count}


@router.get("/status", response_model=list[ShipmentProgressSchema])
def shipment_status(db: Session = Depends(get_db)):
    return get_active_shipments(db)


@router.get("/scans", response_model=list[ScanLogSchema])
def recent_scans(limit: int = 30, db: Session = Depends(get_db)):
    logs = db.query(ScanLog).order_by(ScanLog.scanned_at.desc()).limit(limit).all()
    result = []
    for log in logs:
        ref, qty = None, None
        if log.inventory_label_id:
            inv = db.query(InventoryLabel).filter(InventoryLabel.id == log.inventory_label_id).first()
            if inv:
                ref, qty = inv.reference, float(inv.quantity)
        result.append(ScanLogSchema(
            id=log.id, scanned_value=log.scanned_value, reference=ref,
            quantity=qty, result=log.result.value, scanned_at=log.scanned_at,
        ))
    return result


@router.get("/{shipment_id}/scanned", response_model=list[ScannedLabelSchema])
def shipment_scanned_labels(shipment_id: int, db: Session = Depends(get_db)):
    try:
        return get_scanned_labels(db, shipment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{shipment_id}/scans/{label}")
def remove_scan(shipment_id: int, label: str, db: Session = Depends(get_db)):
    try:
        progress = undo_scan(db, shipment_id, label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ShipmentProgressSchema(**progress)


@router.post("/scan", response_model=ScanResponseSchema)
def global_scan(req: ScanRequest, db: Session = Depends(get_db)):
    try:
        r = process_global_scan(db, req.label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ScanResponseSchema(
        result=r.result, label=r.label, reference=r.reference, quantity=r.quantity,
        scanned_quantity=r.scanned_quantity, remaining_quantity=r.remaining_quantity,
        progress_percent=r.progress_percent, is_complete=r.is_complete,
        shipment_id=r.shipment_id, fifo_date=r.fifo_date,
        success=r.success, already_scanned=r.already_scanned,
    )
