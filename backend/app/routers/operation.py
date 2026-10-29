from decimal import Decimal

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    ShipmentTargetSchema, ShipmentTargetCreateSchema,
    ShipmentFindResultSchema, ShipmentProgressSchema,
    ScanRequest, ScanResponseSchema, ScanLogSchema,
    ShipmentTargetImportResultSchema, RowErrorSchema, ScannedLabelSchema,
    ShipmentManifestSchema, ShipmentGroupSchema, CandidateListSchema,
)
from app.services.target_service import list_targets, add_target, clear_targets, delete_target, find_shipments
from app.services.shipment_excel_import import UNSUITABLE_SHIPMENT, import_shipment_targets_excel
from app.services.shipment_service import (
    get_active_shipments, get_shipment_progress, rename_shipment,
    get_shipment_groups, rename_shipment_group, reorder_shipment_groups,
)
from app.services.recalculate_job import get_recalculate_status, start_recalculate
from app.services.scan_service import process_global_scan
from app.services.operation_service import (
    reset_active_shipments, delete_shipment_group, get_scanned_labels, undo_scan, get_shipment_manifest,
    list_candidate_labels, export_manifest_excel,

)
from app.models import ScanLog, InventoryLabel
from app.ws_manager import ws_manager

router = APIRouter(prefix="/api/shipment", tags=["operation"])


_current_active_group_id: int | None = None


def get_current_active_group_id(db: Session, groups: list[dict] | None = None) -> int | None:
    global _current_active_group_id
    if groups is None:
        groups = get_shipment_groups(db)
    if not groups:
        _current_active_group_id = None
        return None

    if _current_active_group_id is not None and any(g["group_id"] == _current_active_group_id for g in groups):
        return _current_active_group_id

    first_incomplete = next(
        (g["group_id"] for g in groups if not g["is_complete"] and g["scanned_quantity"] < g["requested_quantity"]),
        groups[0]["group_id"]
    )
    _current_active_group_id = first_incomplete
    return _current_active_group_id


def set_current_active_group_id(group_id: int | None):
    global _current_active_group_id
    _current_active_group_id = group_id


def _broadcast_full_status(db: Session, event: str = "sync", extra: dict | None = None):
    """Tüm bağlı istemcilere güncel sevkiyat durumunu ve seçili hedefi broadcast et."""
    groups = get_shipment_groups(db)
    status_list = [item for g in groups for item in g.get("items", [])]
    targets = [ShipmentTargetSchema(id=t.id, reference=t.reference, target_quantity=t.target_quantity).model_dump() for t in list_targets(db)]
    active_gid = get_current_active_group_id(db, groups=groups)

    payload = {
        "groups": groups,
        "shipments": status_list,
        "targets": targets,
        "selected_group_id": active_gid,
    }
    if extra:
        payload.update(extra)
    ws_manager.broadcast_sync(event, payload)


@router.get("/targets", response_model=list[ShipmentTargetSchema])
def get_targets(db: Session = Depends(get_db)):
    return [ShipmentTargetSchema(id=t.id, reference=t.reference, target_quantity=t.target_quantity) for t in list_targets(db)]


@router.post("/targets", response_model=ShipmentTargetSchema)
def create_target(req: ShipmentTargetCreateSchema, db: Session = Depends(get_db)):
    try:
        t = add_target(db, req.reference, req.target_quantity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    result = ShipmentTargetSchema(id=t.id, reference=t.reference, target_quantity=t.target_quantity)
    _broadcast_full_status(db, "target_add")
    return result


@router.delete("/targets")
def delete_targets(db: Session = Depends(get_db)):
    clear_targets(db)
    _broadcast_full_status(db, "target_clear")
    return {"ok": True}


@router.delete("/targets/{target_id}")
def delete_one_target(target_id: int, db: Session = Depends(get_db)):
    try:
        delete_target(db, target_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    _broadcast_full_status(db, "target_delete")
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

    result = import_shipment_targets_excel(db, content, replace=replace, filename=file.filename)
    if any(err.reason == UNSUITABLE_SHIPMENT for err in result.errors):
        raise HTTPException(status_code=400, detail=UNSUITABLE_SHIPMENT)
    if result.missing_columns:
        raise HTTPException(status_code=400, detail=f"Eksik kolonlar: {', '.join(result.missing_columns)}")

    response = ShipmentTargetImportResultSchema(
        total_rows=result.total_rows,
        successful=result.successful,
        error_count=len(result.errors),
        errors=[RowErrorSchema(row=e.row, reason=e.reason) for e in result.errors[:50]],
        missing_columns=result.missing_columns,
        targets=[ShipmentTargetSchema(**t) for t in result.targets],
    )
    _broadcast_full_status(db, "target_import")
    return response


@router.post("/find", response_model=ShipmentFindResultSchema)
def find_shipment_pools(hourly_fifo: bool = False, db: Session = Depends(get_db)):
    try:
        result = find_shipments(db, hourly_fifo=hourly_fifo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    shipments = []
    for s in result["shipments"]:
        prog = get_shipment_progress(db, s["shipment_id"])
        shipments.append(ShipmentProgressSchema(**prog))

    response = ShipmentFindResultSchema(shipments=shipments, errors=result["errors"])
    _broadcast_full_status(db, "find")
    return response


@router.post("/recalculate")
def recalculate_shipment_pools():
    """Hesaplamayı arka planda başlatır. İstek bitmeden arayüz kilitlenmez."""
    return {"status": start_recalculate()}


@router.get("/recalculate/status")
def recalculate_shipment_status():
    return get_recalculate_status()


@router.delete("/group/{group_id}")
def remove_shipment_group(group_id: int, db: Session = Depends(get_db)):
    """Mevcut sevkiyat gruplarından birini kaldırır. Diğerleri ve hedefler durur."""
    try:
        removed = delete_shipment_group(db, group_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if get_current_active_group_id(db) is None:
        set_current_active_group_id(None)
    _broadcast_full_status(db, "group_delete", {"removed_group_id": group_id, "removed": removed})
    return {"removed_group_id": group_id, "removed": removed}


@router.post("/reset")
def reset_shipments(db: Session = Depends(get_db)):
    count = reset_active_shipments(db)
    set_current_active_group_id(None)
    _broadcast_full_status(db, "reset", {"cancelled": count, "selected_group_id": None})
    return {"cancelled": count}


@router.post("/active-group/{group_id}")
def set_active_group_endpoint(group_id: int, db: Session = Depends(get_db)):
    """Aktif hedeflenen sevkiyat grubunu seç ve tüm cihazlara anlık yayınla."""
    groups = get_shipment_groups(db)
    if not any(g["group_id"] == group_id for g in groups):
        raise HTTPException(status_code=404, detail="Sevkiyat grubu bulunamadı")
    set_current_active_group_id(group_id)
    _broadcast_full_status(db, "target_group_changed", {"selected_group_id": group_id})
    return {"selected_group_id": group_id}


@router.get("/active-group")
def get_active_group_endpoint(db: Session = Depends(get_db)):
    """Şu an seçili olan aktif sevkiyat grubu ID'sini döner."""
    return {"selected_group_id": get_current_active_group_id(db)}


@router.get("/status", response_model=list[ShipmentProgressSchema])
def shipment_status(db: Session = Depends(get_db)):
    return get_active_shipments(db)


@router.get("/groups", response_model=list[ShipmentGroupSchema])
def shipment_groups_status(db: Session = Depends(get_db)):
    return get_shipment_groups(db)


@router.get("/manifest", response_model=list[ShipmentManifestSchema])
def shipment_manifest(
    group_id: int | None = None,
    shipment_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Aktif ve tamamlanmış sevkiyatlar için sistemin hesapladığı tam manifest bilgisini döner."""
    return get_shipment_manifest(db, group_id=group_id, shipment_id=shipment_id)


@router.get("/export")
def export_shipment_excel_endpoint(group_id: int | None = None, db: Session = Depends(get_db)):
    """Sevkiyat özetini, okutulan etiketleri ve FIFO planını Excel (.xlsx) olarak indirir."""
    content = export_manifest_excel(db, group_id=group_id)
    filename = f"sevkiyat_raporu_{group_id}.xlsx" if group_id is not None else "sevkiyat_raporu_tumu.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


@router.get("/{shipment_id}/candidates", response_model=CandidateListSchema)
def shipment_candidate_labels(shipment_id: int, fifo_group: str, db: Session = Depends(get_db)):
    """Seçilen FIFO tarihinde okutulabilecek etiketleri döner."""
    try:
        return list_candidate_labels(db, shipment_id, fifo_group)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


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
    result = ShipmentProgressSchema(**progress)
    _broadcast_full_status(db, "undo", {"shipment_id": shipment_id, "label": label})
    return result


@router.post("/scan", response_model=ScanResponseSchema)
def global_scan(req: ScanRequest, db: Session = Depends(get_db)):
    try:
        gid = req.group_id if req.group_id is not None else req.shipment_id
        r = process_global_scan(
            db,
            req.label,
            target_shipment_id=req.shipment_id,
            target_group_id=gid,
            blocked_only=req.blocked_only,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    scan_result = ScanResponseSchema(
        result=r.result, label=r.label, reference=r.reference, quantity=r.quantity,
        scanned_quantity=r.scanned_quantity, remaining_quantity=r.remaining_quantity,
        progress_percent=r.progress_percent, is_complete=r.is_complete,
        shipment_id=r.shipment_id, fifo_date=r.fifo_date,
        success=r.success, already_scanned=r.already_scanned,
        hint=r.hint, expected_fifo_date=r.expected_fifo_date,
        suggested_shipment=r.suggested_shipment,
    )
    _broadcast_full_status(db, "scan", {"scan": scan_result.model_dump()})
    return scan_result


from pydantic import BaseModel as _BaseModel

class _RenameRequest(_BaseModel):
    name: str


class _OrderRequest(_BaseModel):
    group_ids: list[int]


@router.put("/groups/order", response_model=list[ShipmentGroupSchema])
def reorder_groups_endpoint(req: _OrderRequest, db: Session = Depends(get_db)):
    """Sevkiyat listesinin sırasını kullanıcının dizisine göre kaydeder."""
    try:
        groups = reorder_shipment_groups(db, req.group_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _broadcast_full_status(db, "reorder")
    return [ShipmentGroupSchema(**g) for g in groups]


@router.patch("/{shipment_id}/name", response_model=ShipmentProgressSchema)
def rename_shipment_endpoint(shipment_id: int, req: _RenameRequest, db: Session = Depends(get_db)):
    """Sevkiyata veya gruba kullanıcı dostu bir isim ver (ör. 'TIR-1 Yükleme')."""
    try:
        progress = rename_shipment(db, shipment_id, req.name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    _broadcast_full_status(db, "rename", {"shipment_id": shipment_id, "name": req.name})
    return ShipmentProgressSchema(**progress)


@router.patch("/group/{group_id}/name", response_model=list[ShipmentGroupSchema])
def rename_group_endpoint(group_id: int, req: _RenameRequest, db: Session = Depends(get_db)):
    """Sevkiyat grubuna kullanıcı dostu bir isim ver (ör. 'TIR-1 Yükleme')."""
    try:
        groups = rename_shipment_group(db, group_id, req.name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    _broadcast_full_status(db, "rename", {"group_id": group_id, "name": req.name})
    return [ShipmentGroupSchema(**g) for g in groups]
