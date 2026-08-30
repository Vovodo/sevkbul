from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    Shipment, ShipmentStatus,
    ShipmentLabelStatus, ScanLog, ScanResult,
)
from app.services.lookup_cache import lookup_cache
from app.services.shipment_service import complete_shipment_if_ready
from app.services.pool_validation import (
    check_label_in_shipment_pool, PoolCheckResult, log_scan_check,
)


@dataclass
class ScanResponse:
    result: str
    label: str
    reference: str | None
    quantity: float | None
    scanned_quantity: float | None
    remaining_quantity: float | None
    progress_percent: float
    is_complete: bool
    shipment_id: int | None = None
    fifo_date: str | None = None
    success: bool = False
    already_scanned: bool = False


def process_global_scan(
    db: Session,
    scanned_value: str,
    target_shipment_id: int | None = None,
    target_group_id: int | None = None,
) -> ScanResponse:
    label = scanned_value.strip()
    if not label:
        raise ValueError("Etiket boş olamaz")

    active_count = db.query(Shipment).filter(
        Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED])
    ).count()
    if active_count == 0:
        raise ValueError("Önce SEVKİYATI BUL ile havuz oluşturun")

    check = check_label_in_shipment_pool(
        db, label, target_shipment_id=target_shipment_id, target_group_id=target_group_id
    )
    inv = check.inventory

    if check.result == PoolCheckResult.NOT_IN_STOCK:
        log_scan_check(label, None, "N/A", False, "REJECT (NOT_IN_STOCK)")
        _log_scan(db, None, label, None, ScanResult.NOT_FOUND)
        return ScanResponse(
            result=ScanResult.NOT_FOUND.value,
            label=label,
            reference=None,
            quantity=None,
            scanned_quantity=None,
            remaining_quantity=None,
            progress_percent=0,
            is_complete=False,
        )

    fifo_str = inv.fifo_date.strftime("%d.%m.%Y %H:%M") if inv else "N/A"

    actual_label = inv.label if inv else label

    if check.result == PoolCheckResult.ALREADY_SCANNED:
        sid = check.shipment.id if check.shipment else None
        log_scan_check(label, inv.id, fifo_str, True, "REJECT (ALREADY_SCANNED)")
        _log_scan(db, sid, actual_label, inv.id, ScanResult.ALREADY_SCANNED)
        return _build_response(
            ScanResult.ALREADY_SCANNED.value, actual_label, sid, db,
            reference=inv.reference, quantity=float(inv.quantity),
            already_scanned=True,
        )

    if check.result == PoolCheckResult.QUANTITY_EXCEEDED:
        sid = check.shipment.id if check.shipment else None
        log_scan_check(label, inv.id if inv else None, fifo_str, False, "REJECT (QUANTITY_EXCEEDED)")
        _log_scan(db, sid, actual_label, inv.id if inv else None, ScanResult.QUANTITY_EXCEEDED)
        return _build_response(
            ScanResult.QUANTITY_EXCEEDED.value, actual_label, sid, db,
            reference=inv.reference if inv else None,
            quantity=float(inv.quantity) if inv else None,
            fifo_date=fifo_str if inv else None,
        )

    if check.result == PoolCheckResult.IN_POOL and check.shipment and check.shipment_label:
        log_scan_check(label, inv.id, fifo_str, True, "ACCEPT (IN_POOL)")
        return _accept_scan(db, check.shipment.id, actual_label, inv, check.shipment_label)

    sid = check.shipment.id if check.shipment else None
    log_scan_check(label, inv.id if inv else None, fifo_str, False, "REJECT (OUTSIDE_POOL)")
    _log_scan(db, sid, actual_label, inv.id if inv else None, ScanResult.OUTSIDE_SHIPMENT)
    return _build_response(
        ScanResult.OUTSIDE_SHIPMENT.value, actual_label, sid, db,
        reference=inv.reference if inv else None,
        quantity=float(inv.quantity) if inv else None,
    )


def process_scan(db: Session, shipment_id: int, scanned_value: str) -> ScanResponse:
    return process_global_scan(db, scanned_value, target_shipment_id=shipment_id)


def _accept_scan(db, shipment_id: int, label: str, inv, sl) -> ScanResponse:
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not shipment:
        raise ValueError("Sevkiyat bulunamadı")
    if shipment.status == ShipmentStatus.CANCELLED:
        raise ValueError("Sevkiyat iptal edilmiş")
    if shipment.status == ShipmentStatus.COMPLETED:
        _log_scan(db, shipment_id, label, inv.id, ScanResult.QUANTITY_EXCEEDED)
        return _build_response(
            ScanResult.QUANTITY_EXCEEDED.value, label, shipment_id, db,
            reference=inv.reference, quantity=float(inv.quantity),
            fifo_date=inv.fifo_date.strftime("%d.%m.%Y %H:%M") if inv.fifo_date else None,
        )

    if sl.status != ShipmentLabelStatus.PENDING:
        _log_scan(db, shipment_id, label, inv.id, ScanResult.ALREADY_SCANNED)
        return _build_response(
            ScanResult.ALREADY_SCANNED.value, label, shipment_id, db,
            reference=inv.reference, quantity=float(inv.quantity),
            already_scanned=True,
        )

    sl.scanned_quantity = sl.allocated_quantity
    sl.status = ShipmentLabelStatus.SCANNED
    db.commit()

    lookup_cache.mark_scanned(shipment_id, label)
    _log_scan(db, shipment_id, label, inv.id, ScanResult.SHIPMENT_PRODUCT)

    is_complete = complete_shipment_if_ready(db, shipment_id)
    fifo_str = inv.fifo_date.strftime("%d.%m.%Y") if inv else None
    return _build_response(
        ScanResult.SHIPMENT_PRODUCT.value, label, shipment_id, db, is_complete,
        reference=inv.reference, quantity=float(inv.quantity),
        fifo_date=fifo_str, success=True,
    )


def _log_scan(db: Session, shipment_id: int | None, label: str, inv_id: int | None, result: ScanResult):
    log = ScanLog(
        shipment_id=shipment_id,
        inventory_label_id=inv_id,
        scanned_value=label,
        result=result,
        scanned_at=datetime.utcnow(),
    )
    db.add(log)
    db.commit()


def _build_response(
    result: str, label: str, shipment_id: int | None, db: Session,
    is_complete: bool = False, reference: str | None = None, quantity: float | None = None,
    fifo_date: str | None = None, success: bool = False, already_scanned: bool = False,
) -> ScanResponse:
    from app.services.shipment_service import get_shipment_progress
    progress = get_shipment_progress(db, shipment_id) if shipment_id else {}

    return ScanResponse(
        result=result,
        label=label,
        reference=reference or progress.get("reference"),
        quantity=quantity,
        scanned_quantity=progress.get("scanned_quantity"),
        remaining_quantity=progress.get("remaining_quantity"),
        progress_percent=progress.get("progress_percent", 0),
        is_complete=is_complete or progress.get("is_complete", False),
        shipment_id=shipment_id,
        fifo_date=fifo_date,
        success=success or result == ScanResult.SHIPMENT_PRODUCT.value,
        already_scanned=already_scanned or result == ScanResult.ALREADY_SCANNED.value,
    )
