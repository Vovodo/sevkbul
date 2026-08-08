from decimal import Decimal
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import ShipmentTarget, InventoryLabel, Shipment, ShipmentStatus
from app.services.shipment_service import create_shipment_from_reference
from app.services.lookup_cache import lookup_cache


@dataclass
class TargetRow:
    id: int
    reference: str
    target_quantity: float


def list_targets(db: Session) -> list[TargetRow]:
    rows = db.query(ShipmentTarget).order_by(ShipmentTarget.id).all()
    return [
        TargetRow(id=r.id, reference=r.reference, target_quantity=float(r.target_quantity))
        for r in rows
    ]


def add_target(db: Session, reference: str, target_quantity: Decimal) -> TargetRow:
    ref = reference.strip()
    if not ref:
        raise ValueError("Referans boş olamaz")
    if target_quantity <= 0:
        raise ValueError("Miktar geçersiz")

    row = ShipmentTarget(reference=ref, target_quantity=target_quantity)
    db.add(row)
    db.commit()
    db.refresh(row)
    return TargetRow(id=row.id, reference=row.reference, target_quantity=float(row.target_quantity))


def clear_targets(db: Session):
    db.query(ShipmentTarget).delete()
    db.commit()


def find_shipments(db: Session) -> list[dict]:
    """Tüm hedefler için FIFO havuzlarını oluştur."""
    targets = db.query(ShipmentTarget).order_by(ShipmentTarget.id).all()
    if not targets:
        raise ValueError("Sevkiyat hedefi tanımlı değil")

    stock_count = db.query(InventoryLabel).count()
    if stock_count == 0:
        raise ValueError("Önce stok Exceli yükleyin")

    active = db.query(Shipment).filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED])).all()
    for s in active:
        s.status = ShipmentStatus.CANCELLED
        lookup_cache.unload_shipment(s.id)
    db.commit()

    results = []
    errors = []

    for t in targets:
        try:
            created = create_shipment_from_reference(db, t.reference, t.target_quantity)
            results.append({
                "shipment_id": created.shipment_id,
                "reference": created.reference,
                "requested_quantity": float(created.requested_quantity),
                "pool_quantity": float(created.pool_quantity),
                "label_count": created.label_count,
                "insufficient_stock": created.insufficient_stock,
            })
        except ValueError as e:
            errors.append({"reference": t.reference, "error": str(e)})

    if not results and errors:
        raise ValueError(errors[0]["error"])

    db.query(ShipmentTarget).delete()
    db.commit()

    lookup_cache.rebuild_global_index()

    return {"shipments": results, "errors": errors}
