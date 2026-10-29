"""FIFO tarih kotası.

Sevkiyat barkod kilitlemez. Bir tarihte ne kadar mal kabul edeceği saklanır;
o tarihe düşen okutulmamış her etiket, kota dolmadıkça kabul edilir.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    InventoryLabel,
    Shipment,
    ShipmentDateQuota,
    ShipmentLabel,
    ShipmentLabelStatus,
    ShipmentStatus,
)


def group_key(dt: datetime, hourly: bool) -> datetime:
    if hourly:
        return dt.replace(second=0, microsecond=0)
    return datetime(dt.year, dt.month, dt.day)


def format_group(dt: datetime, hourly: bool) -> str:
    if hourly:
        return dt.strftime("%d.%m.%Y %H:%M")
    return dt.strftime("%d.%m.%Y")


def record_quotas(db: Session, shipment_id: int, allocations: list, hourly: bool) -> None:
    buckets: dict[datetime, Decimal] = {}
    for alloc in allocations:
        key = group_key(alloc.fifo_date, hourly)
        buckets[key] = buckets.get(key, Decimal("0")) + Decimal(alloc.allocated_quantity)
    for key, qty in buckets.items():
        if qty <= 0:
            continue
        db.add(ShipmentDateQuota(
            shipment_id=shipment_id,
            fifo_group=key,
            quota_quantity=qty,
        ))


def backfill_missing_quotas(db: Session) -> None:
    """Eski sevkiyatlarda kota satırı yoksa, mevcut tahsisten bir kez üretir."""
    existing = {
        row[0]
        for row in db.query(ShipmentDateQuota.shipment_id).distinct().all()
    }
    shipments = db.query(Shipment).filter(
        Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED])
    ).all()
    changed = False
    for shipment in shipments:
        if shipment.id in existing:
            continue
        rows = (
            db.query(ShipmentLabel, InventoryLabel)
            .join(InventoryLabel, ShipmentLabel.inventory_label_id == InventoryLabel.id)
            .filter(ShipmentLabel.shipment_id == shipment.id)
            .all()
        )
        buckets: dict[datetime, Decimal] = {}
        hourly = bool(shipment.hourly_fifo)
        for sl, inv in rows:
            key = group_key(inv.fifo_date, hourly)
            buckets[key] = buckets.get(key, Decimal("0")) + Decimal(sl.allocated_quantity)
        for key, qty in buckets.items():
            if qty <= 0:
                continue
            db.add(ShipmentDateQuota(
                shipment_id=shipment.id,
                fifo_group=key,
                quota_quantity=qty,
            ))
            changed = True
    if changed:
        db.commit()


def quota_map(db: Session, shipment: Shipment) -> dict[datetime, Decimal]:
    rows = db.query(ShipmentDateQuota).filter(
        ShipmentDateQuota.shipment_id == shipment.id
    ).all()
    hourly = bool(shipment.hourly_fifo)
    return {
        group_key(row.fifo_group, hourly): Decimal(row.quota_quantity)
        for row in rows
    }


def scanned_on_date(db: Session, shipment: Shipment, key: datetime) -> Decimal:
    hourly = bool(shipment.hourly_fifo)
    rows = (
        db.query(ShipmentLabel, InventoryLabel)
        .join(InventoryLabel, ShipmentLabel.inventory_label_id == InventoryLabel.id)
        .filter(
            ShipmentLabel.shipment_id == shipment.id,
            ShipmentLabel.status.in_([ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL]),
        )
        .all()
    )
    total = Decimal("0")
    for sl, inv in rows:
        if group_key(inv.fifo_date, hourly) == key:
            total += Decimal(sl.scanned_quantity or 0)
    return total


def shipment_scanned_total(db: Session, shipment: Shipment) -> Decimal:
    rows = db.query(ShipmentLabel).filter(ShipmentLabel.shipment_id == shipment.id).all()
    return sum(
        (Decimal(sl.scanned_quantity or 0) for sl in rows
         if sl.status in (ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL)),
        Decimal("0"),
    )
