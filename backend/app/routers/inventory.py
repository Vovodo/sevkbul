from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from urllib.parse import quote

from app.database import get_db
from app.schemas import (
    ImportResultSchema, RowErrorSchema, InventoryStatsSchema, ImportPreviewRowSchema,
    InventoryItemSchema, InventoryListResponseSchema,
    ExcelHeaderSettingsSchema, ExcelHeaderInspectResultSchema,
    StoredExcelFileSchema,
)
from app.services.excel_import import import_excel
from app.services.lookup_cache import lookup_cache
from app.services.s3_storage import (
    put_excel_object, get_excel_object, list_excel_objects, delete_excel_object,
)
from app.models import (
    InventoryLabel, Shipment, ShipmentLabel, ShipmentLabelStatus, ShipmentStatus,
    ExcelHeaderSettings,
)
from app.utils.excel_parser import (
    DEFAULT_EXCEL_HEADERS,
    get_excel_header_settings_dict,
    find_column_mapping,
    find_shipment_column_mapping,
)
from app.utils.excel_security import verify_and_sanitize_excel_upload, ExcelSecurityError
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
    try:
        content = await file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Excel dosyası okunamadı")

    try:
        sec_report = verify_and_sanitize_excel_upload(content, file.filename)
    except ExcelSecurityError as sec_err:
        raise HTTPException(status_code=400, detail=str(sec_err))

    result = import_excel(db, content, replace_existing=replace)

    if result.missing_columns:
        raise HTTPException(
            status_code=400,
            detail=f"Eksik kolonlar: {', '.join(result.missing_columns)}",
        )

    # Mini S3: Yalnızca güvenlikten ve şema kontrolünden %100 geçmiş dosyayı kaydet
    put_excel_object(
        db=db,
        slot="stock",
        filename=sec_report.filename,
        content=content,
        row_count=result.successful,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

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

    total = db.query(func.count(InventoryLabel.id)).filter(InventoryLabel.hidden.is_(False)).scalar() or 0
    refs = db.query(func.count(func.distinct(InventoryLabel.reference))).filter(InventoryLabel.hidden.is_(False)).scalar() or 0
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


@router.get("/excel-headers", response_model=ExcelHeaderSettingsSchema)
def get_excel_headers_settings(db: Session = Depends(get_db)):
    """Aktif Excel üst başlık eşleştirme ayarlarını döner."""
    cfg = get_excel_header_settings_dict(db)
    return ExcelHeaderSettingsSchema(**cfg)


@router.put("/excel-headers", response_model=ExcelHeaderSettingsSchema)
def update_excel_headers_settings(
    payload: ExcelHeaderSettingsSchema,
    db: Session = Depends(get_db),
):
    """Excel üst başlık eşleştirme ayarlarını kaydeder."""
    label_h = (payload.label_header or "").strip()
    ref_h = (payload.reference_header or "").strip()
    qty_h = (payload.quantity_header or "").strip()
    fifo_h = (payload.fifo_date_header or "").strip()
    blk_h = (payload.blocked_header or "").strip()
    s_ref_h = (payload.shipment_reference_header or "").strip()
    s_qty_h = (payload.shipment_quantity_header or "").strip()

    if not label_h or not ref_h or not qty_h or not fifo_h:
        raise HTTPException(
            status_code=400,
            detail="Stok Exceli için Etiket, Referans, Miktar ve FIFO Tarihi başlıkları boş bırakılamaz.",
        )
    if not s_ref_h or not s_qty_h:
        raise HTTPException(
            status_code=400,
            detail="Sevkiyat Exceli için Referans ve Miktar başlıkları boş bırakılamaz.",
        )

    from app.utils.excel_parser import normalize_header
    stock_fields = [
        ("Etiket", label_h),
        ("Referans", ref_h),
        ("Miktar", qty_h),
        ("FIFO Tarihi", fifo_h),
    ]
    if blk_h:
        stock_fields.append(("Blokaj", blk_h))

    seen_stock_norms: dict[str, str] = {}
    for fname, fval in stock_fields:
        for part in fval.split(","):
            nh = normalize_header(part)
            if not nh:
                continue
            if nh in seen_stock_norms and seen_stock_norms[nh] != fname:
                raise HTTPException(
                    status_code=400,
                    detail=f"Stok Exceli ayarlarında '{seen_stock_norms[nh]}' ve '{fname}' alanları aynı sütun başlığına ('{part.strip()}') eşleştirilemez.",
                )
            seen_stock_norms[nh] = fname

    s_ref_norms = {normalize_header(p) for p in s_ref_h.split(",") if normalize_header(p)}
    s_qty_norms = {normalize_header(p) for p in s_qty_h.split(",") if normalize_header(p)}
    overlap = s_ref_norms & s_qty_norms
    if overlap:
        raise HTTPException(
            status_code=400,
            detail="Sevkiyat Exceli ayarlarında Referans ve Miktar üst başlıkları aynı olamaz.",
        )

    ExcelHeaderSettings.__table__.create(bind=db.get_bind(), checkfirst=True)
    row = db.query(ExcelHeaderSettings).first()
    if row is None:
        row = ExcelHeaderSettings(
            label_header=label_h,
            reference_header=ref_h,
            quantity_header=qty_h,
            fifo_date_header=fifo_h,
            blocked_header=blk_h,
            shipment_reference_header=s_ref_h,
            shipment_quantity_header=s_qty_h,
        )
        db.add(row)
    else:
        row.label_header = label_h
        row.reference_header = ref_h
        row.quantity_header = qty_h
        row.fifo_date_header = fifo_h
        row.blocked_header = blk_h
        row.shipment_reference_header = s_ref_h
        row.shipment_quantity_header = s_qty_h

    db.commit()
    cfg = get_excel_header_settings_dict(db)
    ws_manager.broadcast_sync("excel_headers_updated", cfg)
    return ExcelHeaderSettingsSchema(**cfg)


@router.post("/excel-headers/reset", response_model=ExcelHeaderSettingsSchema)
def reset_excel_headers_settings(db: Session = Depends(get_db)):
    """Excel üst başlık ayarlarını fabrika varsayılanlarına döndürür."""
    ExcelHeaderSettings.__table__.create(bind=db.get_bind(), checkfirst=True)
    row = db.query(ExcelHeaderSettings).first()
    if row is not None:
        row.label_header = DEFAULT_EXCEL_HEADERS["label_header"]
        row.reference_header = DEFAULT_EXCEL_HEADERS["reference_header"]
        row.quantity_header = DEFAULT_EXCEL_HEADERS["quantity_header"]
        row.fifo_date_header = DEFAULT_EXCEL_HEADERS["fifo_date_header"]
        row.blocked_header = DEFAULT_EXCEL_HEADERS["blocked_header"]
        row.shipment_reference_header = DEFAULT_EXCEL_HEADERS["shipment_reference_header"]
        row.shipment_quantity_header = DEFAULT_EXCEL_HEADERS["shipment_quantity_header"]
        db.commit()
    cfg = get_excel_header_settings_dict(db)
    ws_manager.broadcast_sync("excel_headers_updated", cfg)
    return ExcelHeaderSettingsSchema(**cfg)


@router.post("/excel-headers/inspect", response_model=ExcelHeaderInspectResultSchema)
async def inspect_excel_headers(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Yüklenen örnek Excel dosyasındaki üst başlıkları ve ilk satırları analiz eder."""
    from io import BytesIO
    from openpyxl import load_workbook

    try:
        content = await file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Excel dosyası okunamadı")

    try:
        verify_and_sanitize_excel_upload(content, file.filename)
        wb = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except ExcelSecurityError as sec_err:
        raise HTTPException(status_code=400, detail=str(sec_err))
    except Exception:
        raise HTTPException(status_code=400, detail="Excel dosyası açılamadı")

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True, max_row=6))
    wb.close()
    if not rows:
        raise HTTPException(status_code=400, detail="Excel dosyası boş")

    raw_headers = list(rows[0])
    clean_headers: list[str] = []
    idx_to_header: dict[int, str] = {}
    for idx, h in enumerate(raw_headers):
        if h is not None and str(h).strip():
            txt = str(h).strip()
            clean_headers.append(txt)
            idx_to_header[idx] = txt

    cfg = get_excel_header_settings_dict(db)
    stock_map = find_column_mapping(raw_headers, custom_headers=cfg)
    ship_map = find_shipment_column_mapping(raw_headers, custom_headers=cfg)

    matched_stock = {
        "label": idx_to_header.get(stock_map["label"]) if "label" in stock_map else None,
        "reference": idx_to_header.get(stock_map["reference"]) if "reference" in stock_map else None,
        "quantity": idx_to_header.get(stock_map["quantity"]) if "quantity" in stock_map else None,
        "fifo_date": idx_to_header.get(stock_map["fifo_date"]) if "fifo_date" in stock_map else None,
        "blocked": idx_to_header.get(stock_map["blocked"]) if "blocked" in stock_map else None,
    }
    matched_ship = {
        "reference": idx_to_header.get(ship_map["reference"]) if "reference" in ship_map else None,
        "quantity": idx_to_header.get(ship_map["quantity"]) if "quantity" in ship_map else None,
    }

    sample_rows: list[dict[str, str]] = []
    for r in rows[1:4]:
        if not r or all(c is None or str(c).strip() == "" for c in r):
            continue
        row_dict: dict[str, str] = {}
        for idx, hdr_name in idx_to_header.items():
            val = r[idx] if idx < len(r) else None
            row_dict[hdr_name] = "" if val is None else str(val).strip()
        sample_rows.append(row_dict)

    return ExcelHeaderInspectResultSchema(
        headers=clean_headers,
        matched_stock_columns=matched_stock,
        matched_shipment_columns=matched_ship,
        sample_rows=sample_rows,
    )


@router.get("/storage/files", response_model=list[StoredExcelFileSchema])
def get_stored_excel_files(db: Session = Depends(get_db)):
    """Mini S3 üzerinde saklanan aktif Excel dosyalarının konum ve üstveri bilgilerini döner."""
    items = list_excel_objects(db)
    return [StoredExcelFileSchema(**it) for it in items]


@router.get("/storage/files/{slot}/download")
def download_stored_excel_file(slot: str, db: Session = Depends(get_db)):
    """Mini S3 üzerinde kayıtlı Excel dosyasını ('stock' veya 'shipment') indirir."""
    row = get_excel_object(db, slot)
    if row is None or not row.file_data:
        raise HTTPException(status_code=404, detail="Bu slot için kayıtlı Excel dosyası bulunamadı")
    encoded_name = quote(row.original_filename)
    return Response(
        content=row.file_data,
        media_type=row.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=\"{row.original_filename}\"; filename*=UTF-8''{encoded_name}"
        },
    )


@router.delete("/storage/files/{slot}")
def remove_stored_excel_file(slot: str, db: Session = Depends(get_db)):
    """Mini S3 üzerindeki Excel dosyasını diskten ve PostgreSQL'den siler."""
    deleted = delete_excel_object(db, slot)
    if not deleted:
        raise HTTPException(status_code=404, detail="Silinecek Excel dosyası bulunamadı")
    return {"deleted": True, "slot": slot}



