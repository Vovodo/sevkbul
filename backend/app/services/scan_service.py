from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from decimal import Decimal

from app.models import (
    Shipment, ShipmentStatus, ShipmentLabel,
    ShipmentLabelStatus, ScanLog, ScanResult,
)
from app.services.lookup_cache import lookup_cache
from app.services.shipment_service import complete_shipment_if_ready, rebalance_reference_pending
from app.services.pool_validation import (
    check_label_in_shipment_pool, PoolCheckResult, log_scan_check, _expected_fifo_hint,
)
from app.services.fifo_quota import group_key, quota_map, scanned_on_date, shipment_scanned_total
from app.models import ShipmentDateQuota


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
    hint: str | None = None
    expected_fifo_date: str | None = None
    suggested_shipment: str | None = None


def process_global_scan(
    db: Session,
    scanned_value: str,
    target_shipment_id: int | None = None,
    target_group_id: int | None = None,
    blocked_only: bool = False,
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
        db,
        label,
        target_shipment_id=target_shipment_id,
        target_group_id=target_group_id,
        blocked_only=blocked_only,
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
        other_name = None
        if check.shipment:
            gid = check.shipment.group_id or check.shipment.id
            other_name = check.shipment.group_name or check.shipment.name or f"{gid}. Sevkiyat"
        dup_hint = f"Bu etiket daha önce '{other_name}' içinde okutulmuş." if other_name else None
        return _build_response(
            ScanResult.ALREADY_SCANNED.value, actual_label, sid, db,
            reference=inv.reference, quantity=float(inv.quantity),
            fifo_date=inv.fifo_date.strftime("%d.%m.%Y") if inv else None,
            already_scanned=True,
            hint=dup_hint,
        )

    if check.result == PoolCheckResult.QUANTITY_EXCEEDED:
        sid = check.shipment.id if check.shipment else None
        log_scan_check(label, inv.id if inv else None, fifo_str, False, "REJECT (QUANTITY_EXCEEDED)")
        _log_scan(db, sid, actual_label, inv.id if inv else None, ScanResult.QUANTITY_EXCEEDED)
        exp_date, sug_ship, hint_txt = (
            _expected_fifo_hint(db, inv, check.shipment) if inv else (None, None, None)
        )
        return _build_response(
            ScanResult.QUANTITY_EXCEEDED.value, actual_label, sid, db,
            reference=inv.reference if inv else None,
            quantity=float(inv.quantity) if inv else None,
            fifo_date=inv.fifo_date.strftime("%d.%m.%Y") if inv else None,
            hint=hint_txt,
            expected_fifo_date=exp_date,
            suggested_shipment=sug_ship,
        )

    if check.result == PoolCheckResult.BLOCKED_LABEL:
        sid = check.shipment.id if check.shipment else None
        log_scan_check(label, inv.id if inv else None, fifo_str, False, "REJECT (BLOCKED_LABEL)")
        _log_scan(db, sid, actual_label, inv.id if inv else None, ScanResult.BLOCKED_LABEL)
        return _build_response(
            ScanResult.BLOCKED_LABEL.value, actual_label, sid, db,
            reference=inv.reference if inv else None,
            quantity=float(inv.quantity) if inv else None,
            fifo_date=inv.fifo_date.strftime("%d.%m.%Y") if inv else None,
            hint="Bu etiket stokta BLOKAJLI (DOĞRU). Okutmak için 'Sadece Blokajlıları Oku' butonunu açın.",
        )

    if check.result == PoolCheckResult.NOT_BLOCKED_LABEL:
        sid = check.shipment.id if check.shipment else None
        log_scan_check(label, inv.id if inv else None, fifo_str, False, "REJECT (NOT_BLOCKED_LABEL)")
        _log_scan(db, sid, actual_label, inv.id if inv else None, ScanResult.NOT_BLOCKED_LABEL)
        return _build_response(
            ScanResult.NOT_BLOCKED_LABEL.value, actual_label, sid, db,
            reference=inv.reference if inv else None,
            quantity=float(inv.quantity) if inv else None,
            fifo_date=inv.fifo_date.strftime("%d.%m.%Y") if inv else None,
            hint="'Sadece Blokajlıları Oku' modu açık — Bu etiket blokajsız (YANLIŞ) olduğu için reddedildi.",
        )

    if check.result == PoolCheckResult.IN_POOL and check.shipment:
        log_scan_check(label, inv.id, fifo_str, True, "ACCEPT (IN_POOL)")
        return _accept_scan(db, check.shipment.id, actual_label, inv, check.shipment_label, blocked_only=blocked_only)

    sid = check.shipment.id if check.shipment else None
    log_scan_check(label, inv.id if inv else None, fifo_str, False, "REJECT (OUTSIDE_POOL)")
    _log_scan(db, sid, actual_label, inv.id if inv else None, ScanResult.OUTSIDE_SHIPMENT)
    exp_date, sug_ship, hint_txt = (
        _expected_fifo_hint(db, inv, check.shipment) if inv else (None, None, None)
    )
    return _build_response(
        ScanResult.OUTSIDE_SHIPMENT.value, actual_label, sid, db,
        reference=inv.reference if inv else None,
        quantity=float(inv.quantity) if inv else None,
        fifo_date=inv.fifo_date.strftime("%d.%m.%Y") if inv else None,
        hint=hint_txt,
        expected_fifo_date=exp_date,
        suggested_shipment=sug_ship,
    )


def process_scan(db: Session, shipment_id: int, scanned_value: str, blocked_only: bool = False) -> ScanResponse:
    return process_global_scan(db, scanned_value, target_shipment_id=shipment_id, blocked_only=blocked_only)


def _accept_scan(db, shipment_id: int, label: str, inv, sl, blocked_only: bool = False) -> ScanResponse:
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

    if sl is not None and sl.status != ShipmentLabelStatus.PENDING:
        _log_scan(db, shipment_id, label, inv.id, ScanResult.ALREADY_SCANNED)
        return _build_response(
            ScanResult.ALREADY_SCANNED.value, label, shipment_id, db,
            reference=inv.reference, quantity=float(inv.quantity),
            already_scanned=True,
        )

    key = group_key(inv.fifo_date, bool(shipment.hourly_fifo))
    remaining = quota_map(db, shipment).get(key, Decimal("0")) - scanned_on_date(db, shipment, key)
    take = min(Decimal(inv.quantity), remaining)
    if take <= Decimal("0.001"):
        _log_scan(db, shipment_id, label, inv.id, ScanResult.QUANTITY_EXCEEDED)
        return _build_response(
            ScanResult.QUANTITY_EXCEEDED.value, label, shipment_id, db,
            reference=inv.reference, quantity=float(inv.quantity),
            fifo_date=inv.fifo_date.strftime("%d.%m.%Y %H:%M") if inv.fifo_date else None,
        )

    need_rebalance = sl is None or Decimal(sl.allocated_quantity) != take
    if sl is None:
        sl = ShipmentLabel(
            shipment_id=shipment_id,
            inventory_label_id=inv.id,
            allocated_quantity=take,
            scanned_quantity=Decimal("0"),
            status=ShipmentLabelStatus.PENDING,
        )
        db.add(sl)
        db.flush()

    sl.scanned_quantity = take
    sl.status = ShipmentLabelStatus.SCANNED
    sl.allocated_quantity = take
    db.flush()

    # Tahmin listesindeki kilit kalkar; kota satırı durur.
    deleted_other = db.query(ShipmentLabel).filter(
        ShipmentLabel.inventory_label_id == inv.id,
        ShipmentLabel.id != sl.id,
        ShipmentLabel.status == ShipmentLabelStatus.PENDING,
    ).delete(synchronize_session="fetch")

    if need_rebalance or deleted_other > 0:
        rebalance_reference_pending(db, inv.reference)

    log = ScanLog(
        shipment_id=shipment_id,
        inventory_label_id=inv.id,
        scanned_value=label,
        result=ScanResult.SHIPMENT_PRODUCT,
        scanned_at=datetime.utcnow(),
    )
    db.add(log)
    db.flush()

    total_scanned_now = shipment_scanned_total(db, shipment)
    is_complete = False
    if total_scanned_now >= Decimal(shipment.requested_quantity) and shipment.status == ShipmentStatus.ACTIVE:
        shipment.status = ShipmentStatus.COMPLETED
        shipment.completed_at = datetime.utcnow()
        is_complete = True
    elif shipment.status == ShipmentStatus.COMPLETED:
        is_complete = True

    db.commit()

    lookup_cache.mark_scanned(shipment_id, label)
    fifo_str = inv.fifo_date.strftime("%d.%m.%Y") if inv else None
    req_f = float(shipment.requested_quantity)
    scan_f = float(total_scanned_now)
    rem_f = max(0.0, req_f - scan_f)
    pct_f = round(min((scan_f / req_f * 100.0) if req_f > 0 else 0.0, 100.0), 1)
    return ScanResponse(
        result=ScanResult.SHIPMENT_PRODUCT.value,
        label=label,
        reference=inv.reference,
        quantity=float(inv.quantity),
        scanned_quantity=scan_f,
        remaining_quantity=rem_f,
        progress_percent=pct_f,
        is_complete=is_complete,
        shipment_id=shipment_id,
        fifo_date=fifo_str,
        success=True,
        already_scanned=False,
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
    hint: str | None = None, expected_fifo_date: str | None = None,
    suggested_shipment: str | None = None,
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
        hint=hint,
        expected_fifo_date=expected_fifo_date,
        suggested_shipment=suggested_shipment,
    )
