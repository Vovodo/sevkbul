from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    ImportResultSchema, RowErrorSchema, InventoryStatsSchema, ImportPreviewRowSchema,
    InventoryItemSchema, InventoryListResponseSchema,
)
from app.services.excel_import import import_excel
from app.services.lookup_cache import lookup_cache
from app.models import InventoryLabel, Shipment, ShipmentLabel, ShipmentLabelStatus, ShipmentStatus
from app.ws_manager import ws_manager
from sqlalchemy import func, or_
from pydantic import BaseModel as _BaseModel

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


@router.post("/import/stock", response_model=ImportResultSchema)
async def upload_stock_excel(
    file: UploadFile = File(...),
    replace: bool = True,
    db: Session = Depends(get_db),
):
    """Stok Exceli: ETİKET, REFERANS, MİKTAR, X98FIFO_TARIH"""
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Geçersiz dosya formatı. Excel (.xlsx) yükleyin.")

    try:
        content = await file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Excel dosyası okunamadı")

    result = import_excel(db, content, replace_existing=replace)

    if result.missing_columns:
        raise HTTPException(
            status_code=400,
            detail=f"Eksik kolonlar: {', '.join(result.missing_columns)}",
        )

    lookup_cache.reload_inventory_labels(db)

    total = db.query(func.count(InventoryLabel.id)).scalar() or 0
    refs = db.query(func.count(func.distinct(InventoryLabel.reference))).scalar() or 0
    ws_manager.broadcast_sync("stock_import", {
        "total_labels": total,
        "total_references": refs,
        "successful": result.successful,
    })

    return ImportResultSchema(
        total_rows=result.total_rows,
        successful=total if not replace else result.successful,
        error_count=len(result.errors),
        duplicate_count=len(result.duplicate_labels),
        invalid_label_count=result.invalid_label_count,
        invalid_reference_count=result.invalid_reference_count,
        invalid_quantity_count=result.invalid_quantity_count,
        invalid_fifo_date_count=result.invalid_fifo_date_count,
        errors=[RowErrorSchema(row=e.row, reason=e.reason, error_type=e.error_type) for e in result.errors[:100]],
        duplicate_labels=result.duplicate_labels[:50],
        missing_columns=result.missing_columns,
        preview_rows=[
            ImportPreviewRowSchema(
                label=p.label,
                reference=p.reference,
                quantity=p.quantity,
                fifo_date=p.fifo_date,
            )
            for p in result.preview_rows
        ],
    )


@router.post("/import", response_model=ImportResultSchema)
async def upload_excel(
    file: UploadFile = File(...),
    replace: bool = True,
    db: Session = Depends(get_db),
):
    """Geriye uyumluluk: stok Excel import"""
    return await upload_stock_excel(file, replace, db)


@router.get("/stats", response_model=InventoryStatsSchema)
def get_inventory_stats(db: Session = Depends(get_db)):
    total = db.query(func.count(InventoryLabel.id)).scalar() or 0
    refs = db.query(func.count(func.distinct(InventoryLabel.reference))).scalar() or 0
    blocked = db.query(func.count(InventoryLabel.id)).filter(InventoryLabel.blocked.is_(True)).scalar() or 0
    hidden = db.query(func.count(InventoryLabel.id)).filter(InventoryLabel.hidden.is_(True)).scalar() or 0
    return InventoryStatsSchema(
        total_labels=total,
        total_references=refs,
        blocked_labels=blocked,
        unblocked_labels=max(0, total - blocked),
        hidden_labels=hidden,
    )


class _ToggleHiddenRequest(_BaseModel):
    hidden: bool


class _BulkToggleHiddenRequest(_BaseModel):
    label_ids: list[int]
    hidden: bool


@router.get("/labels", response_model=InventoryListResponseSchema)
def list_inventory_labels(
    q: str = "",
    filter_mode: str = "all",
    limit: int = 10000,
    db: Session = Depends(get_db),
):
    """
    Stok Excelindeki etiketleri listeler (salt-okunur içerik + gizle/göster durumu).
    filter_mode: all | active | hidden | blocked
    """
    total = db.query(func.count(InventoryLabel.id)).scalar() or 0
    hidden_count = db.query(func.count(InventoryLabel.id)).filter(InventoryLabel.hidden.is_(True)).scalar() or 0
    blocked_count = db.query(func.count(InventoryLabel.id)).filter(InventoryLabel.blocked.is_(True)).scalar() or 0
    active_count = max(0, total - hidden_count)

    query = db.query(InventoryLabel)
    search = q.strip()
    if search:
        like_pat = f"%{search}%"
        query = query.filter(
            or_(
                InventoryLabel.label.ilike(like_pat),
                InventoryLabel.reference.ilike(like_pat),
            )
        )

    if filter_mode == "active":
        query = query.filter(InventoryLabel.hidden.is_(False))
    elif filter_mode == "hidden":
        query = query.filter(InventoryLabel.hidden.is_(True))
    elif filter_mode == "blocked":
        query = query.filter(InventoryLabel.blocked.is_(True))

    rows = (
        query.order_by(
            InventoryLabel.hidden.desc(),
            InventoryLabel.reference.asc(),
            InventoryLabel.fifo_date.asc(),
            InventoryLabel.id.asc(),
        )
        .limit(min(max(limit, 1), 20000))
        .all()
    )

    scanned_ids: set[int] = set()
    if rows:
        scanned_ids = {
            r[0]
            for r in db.query(ShipmentLabel.inventory_label_id)
            .join(Shipment, ShipmentLabel.shipment_id == Shipment.id)
            .filter(
                ShipmentLabel.inventory_label_id.in_([row.id for row in rows]),
                ShipmentLabel.status.in_([ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL]),
                Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]),
            )
            .all()
        }

    items = [
        InventoryItemSchema(
            id=row.id,
            label=row.label,
            reference=row.reference,
            quantity=float(row.quantity),
            fifo_date=row.fifo_date.strftime("%d.%m.%Y %H:%M"),
            blocked=bool(row.blocked),
            hidden=bool(row.hidden),
            scanned=row.id in scanned_ids,
        )
        for row in rows
    ]

    return InventoryListResponseSchema(
        total=total,
        active_count=active_count,
        hidden_count=hidden_count,
        blocked_count=blocked_count,
        items=items,
    )


@router.patch("/labels/bulk-hidden")
def set_inventory_labels_bulk_hidden(
    req: _BulkToggleHiddenRequest,
    db: Session = Depends(get_db),
):
    """
    Filtrelenen birden fazla etiketi (okutulmamış olanları) tek seferde gizliye alır veya aktif eder.
    Ardından açık sevkiyatları tek seferde yeniden hesaplar.
    """
    ids = list(set(req.label_ids or []))
    if not ids:
        return {"updated": 0, "hidden": bool(req.hidden)}

    # Okutulmuş etiketler gizlenemez
    scanned_ids = {
        r[0]
        for r in db.query(ShipmentLabel.inventory_label_id)
        .join(Shipment, ShipmentLabel.shipment_id == Shipment.id)
        .filter(
            ShipmentLabel.inventory_label_id.in_(ids),
            ShipmentLabel.status.in_([ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL]),
            Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]),
        )
        .all()
    }
    target_ids = [i for i in ids if i not in scanned_ids]
    if not target_ids:
        return {"updated": 0, "hidden": bool(req.hidden)}

    updated_count = (
        db.query(InventoryLabel)
        .filter(InventoryLabel.id.in_(target_ids))
        .update({InventoryLabel.hidden: bool(req.hidden)}, synchronize_session="fetch")
    )
    db.commit()

    has_active_shipments = (
        db.query(Shipment.id)
        .filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]))
        .first()
        is not None
    )
    if has_active_shipments:
        from app.services.shipment_service import recalculate_shipments
        from app.routers.operation import _broadcast_full_status

        recalculate_shipments(db)
        _broadcast_full_status(db, "recalculate")
    else:
        lookup_cache.reload_inventory_labels(db)

    return {"updated": int(updated_count), "hidden": bool(req.hidden)}


@router.patch("/labels/{label_id}/hidden", response_model=InventoryItemSchema)
def set_inventory_label_hidden(
    label_id: int,
    req: _ToggleHiddenRequest,
    db: Session = Depends(get_db),
):
    """
    Etiketin içerik bilgilerini değiştirmeden sadece gizlilik (hidden) durumunu günceller.
    Gizlenen etiket sevkiyat FIFO hesaplamasına dahil edilmez; açık sevkiyatlar otomatik yeniden hesaplanır.
    """
    inv = db.query(InventoryLabel).filter(InventoryLabel.id == label_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Etiket bulunamadı")

    inv.hidden = bool(req.hidden)
    db.commit()
    db.refresh(inv)

    has_active_shipments = (
        db.query(Shipment.id)
        .filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]))
        .first()
        is not None
    )
    if has_active_shipments:
        from app.services.shipment_service import recalculate_shipments
        from app.routers.operation import _broadcast_full_status

        recalculate_shipments(db)
        _broadcast_full_status(db, "recalculate")
    else:
        lookup_cache.reload_inventory_labels(db)

    is_scanned = (
        db.query(ShipmentLabel.id)
        .join(Shipment, ShipmentLabel.shipment_id == Shipment.id)
        .filter(
            ShipmentLabel.inventory_label_id == inv.id,
            ShipmentLabel.status.in_([ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL]),
            Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]),
        )
        .first()
        is not None
    )

    return InventoryItemSchema(
        id=inv.id,
        label=inv.label,
        reference=inv.reference,
        quantity=float(inv.quantity),
        fifo_date=inv.fifo_date.strftime("%d.%m.%Y %H:%M"),
        blocked=bool(inv.blocked),
        hidden=bool(inv.hidden),
        scanned=is_scanned,
    )


@router.get("/debug/reference/{reference}")
def debug_reference_labels(reference: str, db: Session = Depends(get_db)):
    """
    Tanılama: Bir referans için DB'deki TÜM etiketleri FIFO tarih sırasıyla listeler.
    Bu, FIFO havuz seçiminin doğruluğunu doğrulamak için kullanılır.
    """
    labels = (
        db.query(InventoryLabel)
        .filter(InventoryLabel.reference == reference)
        .order_by(InventoryLabel.fifo_date.asc())
        .all()
    )

    items = []
    cumulative = 0.0
    for idx, l in enumerate(labels, 1):
        qty = float(l.quantity)
        cumulative += qty
        items.append({
            "sira": idx,
            "label": l.label,
            "reference": l.reference,
            "quantity": qty,
            "fifo_date": l.fifo_date.strftime("%d.%m.%Y %H:%M:%S"),
            "fifo_date_raw": l.fifo_date.isoformat(),
            "cumulative_qty": cumulative,
        })

    return {
        "reference": reference,
        "total_labels": len(items),
        "total_quantity": cumulative,
        "items": items,
    }

