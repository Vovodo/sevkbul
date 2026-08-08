from decimal import Decimal
from datetime import datetime
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import (
    InventoryLabel, Shipment, ShipmentLabel, ShipmentStatus,
    ShipmentLabelStatus,
)
from app.services.fifo_engine import calculate_fifo_groups, InventoryItem
from app.services.lookup_cache import lookup_cache
from app.services.pool_validation import log_allocation_created


@dataclass
class ShipmentCreateResult:
    shipment_id: int
    reference: str
    requested_quantity: Decimal
    pool_quantity: Decimal
    label_count: int
    insufficient_stock: bool
    remaining_unfulfilled: Decimal
    fifo_group_count: int


def create_shipment_from_reference(
    db: Session,
    reference: str,
    requested_quantity: Decimal,
) -> ShipmentCreateResult:
    labels = (
        db.query(InventoryLabel)
        .filter(InventoryLabel.reference == reference)
        .order_by(InventoryLabel.fifo_date.asc())
        .all()
    )

    if not labels:
        raise ValueError(f"Referans stokta bulunamadı: {reference}")

    items = [
        InventoryItem(
            label=l.label,
            reference=l.reference,
            quantity=l.quantity,
            fifo_date=l.fifo_date,
            id=l.id,
        )
        for l in labels
    ]

    fifo_result = calculate_fifo_groups(items, requested_quantity)

    if not fifo_result.allocations:
        raise ValueError(f"Yeterli stok yok: {reference}")

    shipment = Shipment(
        reference=reference,
        requested_quantity=requested_quantity,
        status=ShipmentStatus.ACTIVE,
    )
    db.add(shipment)
    db.flush()

    for alloc in fifo_result.allocations:
        sl = ShipmentLabel(
            shipment_id=shipment.id,
            inventory_label_id=alloc.inventory_label_id,
            allocated_quantity=alloc.allocated_quantity,
            scanned_quantity=Decimal(0),
            status=ShipmentLabelStatus.PENDING,
        )
        db.add(sl)

    db.commit()
    db.refresh(shipment)

    log_allocation_created(
        shipment.id, reference, float(requested_quantity), fifo_result.allocations
    )
    lookup_cache.load_shipment(db, shipment.id)

    return ShipmentCreateResult(
        shipment_id=shipment.id,
        reference=reference,
        requested_quantity=requested_quantity,
        pool_quantity=fifo_result.pool_quantity,
        label_count=len(fifo_result.allocations),
        insufficient_stock=fifo_result.remaining_unfulfilled > 0,
        remaining_unfulfilled=fifo_result.remaining_unfulfilled,
        fifo_group_count=len(fifo_result.included_group_dates),
    )


def create_shipment(db: Session, reference: str, requested_quantity: Decimal) -> ShipmentCreateResult:
    return create_shipment_from_reference(db, reference, requested_quantity)


def get_shipment_progress(db: Session, shipment_id: int) -> dict:
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not shipment:
        raise ValueError("Sevkiyat bulunamadı")

    all_labels = (
        db.query(ShipmentLabel)
        .filter(ShipmentLabel.shipment_id == shipment_id)
        .all()
    )

    requested = float(shipment.requested_quantity)
    pool_f = requested

    scanned_qty = sum(
        sl.scanned_quantity for sl in all_labels
        if sl.status in (ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL)
    )

    scanned_f = float(scanned_qty)
    remaining_target = max(0, requested - scanned_f)
    progress = (scanned_f / requested * 100) if requested > 0 else 0

    return {
        "shipment_id": shipment.id,
        "reference": shipment.reference,
        "requested_quantity": requested,
        "pool_quantity": pool_f,
        "scanned_quantity": scanned_f,
        "remaining_quantity": remaining_target,
        "progress_percent": round(min(progress, 100), 1),
        "status": shipment.status.value,
        "is_complete": shipment.status == ShipmentStatus.COMPLETED,
    }


def complete_shipment_if_ready(db: Session, shipment_id: int) -> bool:
    progress = get_shipment_progress(db, shipment_id)
    if progress["remaining_quantity"] <= 0 and progress["status"] == "active":
        shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
        if shipment:
            shipment.status = ShipmentStatus.COMPLETED
            shipment.completed_at = datetime.utcnow()
            db.commit()
            return True
    return False


def get_active_shipments(db: Session) -> list[dict]:
    shipments = (
        db.query(Shipment)
        .filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]))
        .order_by(Shipment.created_at.desc())
        .all()
    )
    return [get_shipment_progress(db, s.id) for s in shipments]
