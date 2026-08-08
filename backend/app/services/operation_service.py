from sqlalchemy.orm import Session, joinedload

from app.models import (
    Shipment, ShipmentLabel, ShipmentStatus, ShipmentLabelStatus,
    ScanLog, ScanResult, InventoryLabel,
)
from app.services.lookup_cache import lookup_cache
from app.services.shipment_service import get_shipment_progress


def reset_active_shipments(db: Session) -> int:
    """Aktif ve tamamlanmış tüm sevkiyatları iptal et ve cache'i temizle."""
    active = db.query(Shipment).filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED])).all()
    count = len(active)
    for s in active:
        s.status = ShipmentStatus.CANCELLED
        lookup_cache.unload_shipment(s.id)
    db.commit()
    lookup_cache.rebuild_global_index()
    return count


def get_scanned_labels(db: Session, shipment_id: int) -> list[dict]:
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not shipment:
        raise ValueError("Sevkiyat bulunamadı")

    sls = (
        db.query(ShipmentLabel)
        .options(joinedload(ShipmentLabel.inventory_label))
        .filter(
            ShipmentLabel.shipment_id == shipment_id,
            ShipmentLabel.status == ShipmentLabelStatus.SCANNED,
        )
        .all()
    )

    result = []
    for sl in sls:
        inv = sl.inventory_label
        if not inv:
            continue
        log = (
            db.query(ScanLog)
            .filter(
                ScanLog.shipment_id == shipment_id,
                ScanLog.scanned_value == inv.label,
                ScanLog.result == ScanResult.SHIPMENT_PRODUCT,
            )
            .order_by(ScanLog.scanned_at.desc())
            .first()
        )
        result.append({
            "label": inv.label,
            "quantity": float(sl.allocated_quantity),
            "fifo_date": inv.fifo_date.strftime("%d.%m.%Y"),
            "scanned_at": log.scanned_at.isoformat() if log else None,
        })

    result.sort(key=lambda x: x.get("scanned_at") or "", reverse=True)
    return result


from app.services.pool_validation import find_inventory_label


def undo_scan(db: Session, shipment_id: int, label: str) -> dict:
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not shipment:
        raise ValueError("Sevkiyat bulunamadı")

    if shipment.status == ShipmentStatus.CANCELLED:
        raise ValueError("Sevkiyat iptal edilmiş")

    inv = find_inventory_label(db, label)
    target_label = inv.label if inv else label.strip()

    sl = (
        db.query(ShipmentLabel)
        .join(InventoryLabel)
        .filter(
            ShipmentLabel.shipment_id == shipment_id,
            InventoryLabel.label == target_label,
        )
        .first()
    )

    if not sl or sl.status != ShipmentLabelStatus.SCANNED:
        raise ValueError("Bu etiket okutulmuş olarak kayıtlı değil")

    was_completed = shipment.status == ShipmentStatus.COMPLETED

    sl.scanned_quantity = 0
    sl.status = ShipmentLabelStatus.PENDING

    if was_completed:
        shipment.status = ShipmentStatus.ACTIVE
        shipment.completed_at = None

    db.query(ScanLog).filter(
        ScanLog.shipment_id == shipment_id,
        ScanLog.scanned_value == label.strip(),
        ScanLog.result == ScanResult.SHIPMENT_PRODUCT,
    ).delete()

    db.commit()

    if shipment.status == ShipmentStatus.ACTIVE:
        if was_completed:
            lookup_cache.load_shipment(db, shipment_id)
        else:
            lookup_cache.unmark_scanned(shipment_id, label.strip())

    return get_shipment_progress(db, shipment_id)
