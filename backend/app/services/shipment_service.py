from decimal import Decimal
from datetime import datetime
from dataclasses import dataclass

from sqlalchemy import func
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


def _get_previously_allocated(
    db: Session,
    reference: str,
    exclude_shipment_id: int | None = None,
) -> dict[int, Decimal]:
    """
    Belirtilen referans için aktif/tamamlanmış tüm sevkiyatlardaki
    inventory_label_id → toplam allocated_quantity haritasını döner.

    Bu sayede yeni sevkiyat oluşturulurken FIFO motoru:
        kullanılabilir_miktar = toplam_stok - önceki_tahsisler
    ile çalışır.

    exclude_shipment_id: Bu sevkiyatın kendi tahsislerini hariç tut
    (undo/yeniden hesaplama senaryoları için).
    """
    query = (
        db.query(
            ShipmentLabel.inventory_label_id,
            func.sum(ShipmentLabel.allocated_quantity).label("total_allocated"),
        )
        .join(Shipment, ShipmentLabel.shipment_id == Shipment.id)
        .filter(
            Shipment.reference == reference,
            Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]),
        )
        .group_by(ShipmentLabel.inventory_label_id)
    )

    if exclude_shipment_id is not None:
        query = query.filter(ShipmentLabel.shipment_id != exclude_shipment_id)

    rows = query.all()
    return {
        row.inventory_label_id: Decimal(str(row.total_allocated))
        for row in rows
    }


def create_shipment_from_reference(
    db: Session,
    reference: str,
    requested_quantity: Decimal,
    hourly_fifo: bool = False,
) -> "ShipmentCreateResult":
    labels = (
        db.query(InventoryLabel)
        .filter(InventoryLabel.reference == reference)
        .order_by(InventoryLabel.fifo_date.asc())
        .all()
    )

    if not labels:
        raise ValueError(f"Referans stokta bulunamadı: {reference}")

    # ── ÇOKLU SEVKİYAT FIFO DEVAMLILIĞI ──────────────────────────────────
    # Aynı referans için önceki aktif/tamamlanmış sevkiyatlarda tahsis
    # edilmiş miktarları hesapla. FIFO motoru bu miktarları stoktan düşerek
    # kaldığı yerden devam eder. Stok kayıtları silinmez.
    previously_allocated = _get_previously_allocated(db, reference)

    items = []
    for lbl in labels:
        used = previously_allocated.get(lbl.id, Decimal("0"))
        available = lbl.quantity - used
        if available > Decimal("0"):
            items.append(
                InventoryItem(
                    label=lbl.label,
                    reference=lbl.reference,
                    quantity=available,   # ← Kalan kullanılabilir miktar
                    fifo_date=lbl.fifo_date,
                    id=lbl.id,
                )
            )
    # ─────────────────────────────────────────────────────────────────────

    if not items:
        raise ValueError(
            f"Bu referans için kullanılabilir stok kalmadı: {reference}. "
            "Tüm miktarlar önceki sevkiyatlara tahsis edildi."
        )

    fifo_result = calculate_fifo_groups(items, requested_quantity, hourly_fifo=hourly_fifo)

    if not fifo_result.allocations:
        raise ValueError(f"Yeterli stok yok: {reference}")

    shipment = Shipment(
        reference=reference,
        requested_quantity=requested_quantity,
        status=ShipmentStatus.ACTIVE,
        hourly_fifo=hourly_fifo,
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


def create_shipment(
    db: Session,
    reference: str,
    requested_quantity: Decimal,
    hourly_fifo: bool = False,
) -> ShipmentCreateResult:
    return create_shipment_from_reference(db, reference, requested_quantity, hourly_fifo=hourly_fifo)


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
