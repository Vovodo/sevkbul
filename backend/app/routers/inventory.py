from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ImportResultSchema, RowErrorSchema, InventoryStatsSchema, ImportPreviewRowSchema
from app.services.excel_import import import_excel
from app.services.lookup_cache import lookup_cache
from app.models import InventoryLabel
from app.ws_manager import ws_manager
from sqlalchemy import func

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
        successful=result.successful,
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
    return InventoryStatsSchema(total_labels=total, total_references=refs)
