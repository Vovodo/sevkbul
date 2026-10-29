from decimal import Decimal
from dataclasses import dataclass

from sqlalchemy import func
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


def add_target(
    db: Session,
    reference: str,
    target_quantity: Decimal,
    source_name: str | None = None,
) -> TargetRow:
    ref = reference.strip()
    if not ref:
        raise ValueError("Referans boş olamaz")
    if target_quantity <= 0:
        raise ValueError("Miktar geçersiz")

    existing = (
        db.query(ShipmentTarget)
        .filter(func.upper(func.trim(ShipmentTarget.reference)) == ref.upper())
        .first()
    )
    if existing:
        existing.target_quantity = Decimal(existing.target_quantity) + Decimal(target_quantity)
        if source_name and not existing.source_name:
            existing.source_name = source_name
        db.commit()
        db.refresh(existing)
        return TargetRow(id=existing.id, reference=existing.reference, target_quantity=float(existing.target_quantity))

    row = ShipmentTarget(reference=ref, target_quantity=target_quantity, source_name=source_name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return TargetRow(id=row.id, reference=row.reference, target_quantity=float(row.target_quantity))


def clear_targets(db: Session):
    db.query(ShipmentTarget).delete()
    db.commit()


def delete_target(db: Session, target_id: int) -> None:
    row = db.query(ShipmentTarget).filter(ShipmentTarget.id == target_id).first()
    if row is None:
        raise ValueError("Hedef bulunamadı")
    db.delete(row)
    db.commit()


def find_shipments(db: Session, hourly_fifo: bool = False) -> list[dict]:
    """
    Tüm hedefler için FIFO havuzlarını oluştur.

    ── ÇOKLU SEVKİYAT FIFO DEVAMLILIĞI ──────────────────────────────────
    Önceki sürümde bu fonksiyon, her çağrıda mevcut aktif/tamamlanmış
    sevkiyatları CANCELLED yaparak sıfırlıyordu.

    Yeni davranış:
    - Önceki sevkiyatlar KORUNUR ve iptal edilmez.
    - Her referans için `create_shipment_from_reference()` çağrılınca,
      önceki sevkiyatlarda tahsis edilmiş miktarlar otomatik olarak
      kullanılabilir stoktan düşülür (shipment_service._get_previously_allocated).
    - FIFO sıralama ve tarih/saat önceliği aynen korunur.
    - Sıfırlamak için kullanıcı "Sevkiyatı Sıfırla" butonunu kullanır.
    ──────────────────────────────────────────────────────────────────────
    """
    targets = db.query(ShipmentTarget).order_by(ShipmentTarget.id).all()
    if not targets:
        raise ValueError("Sevkiyat hedefi tanımlı değil")

    stock_count = db.query(InventoryLabel).count()
    if stock_count == 0:
        raise ValueError("Önce stok Exceli yükleyin")

    # NOT: Önceki sevkiyatlar artık iptal edilmiyor.
    # FIFO devamlılığı sayesinde yeni sevkiyatlar kaldığı yerden başlar.

    # Bu batch'teki tüm referanslar TEK BİR SEVKİYAT GRUBU'na aittir (1. Sevkiyat, 2. Sevkiyat...)
    max_gid = db.query(func.max(Shipment.group_id)).scalar()
    next_group_id = (max_gid or 0) + 1
    named = next((t.source_name for t in targets if t.source_name), None)
    group_name = named or f"{next_group_id}. Sevkiyat"

    results = []
    errors = []

    merged_targets: list[tuple[str, Decimal]] = []
    seen_refs: dict[str, int] = {}
    for t in targets:
        rkey = t.reference.strip().upper()
        if rkey in seen_refs:
            idx = seen_refs[rkey]
            merged_targets[idx] = (merged_targets[idx][0], merged_targets[idx][1] + Decimal(t.target_quantity))
        else:
            seen_refs[rkey] = len(merged_targets)
            merged_targets.append((t.reference.strip(), Decimal(t.target_quantity)))

    for ref_val, qty_val in merged_targets:
        try:
            created = create_shipment_from_reference(
                db, ref_val, qty_val, hourly_fifo=hourly_fifo,
                group_id=next_group_id, group_name=group_name
            )
            results.append({
                "shipment_id": created.shipment_id,
                "group_id": next_group_id,
                "reference": created.reference,
                "requested_quantity": float(created.requested_quantity),
                "pool_quantity": float(created.pool_quantity),
                "label_count": created.label_count,
                "insufficient_stock": created.insufficient_stock,
            })
        except ValueError as e:
            errors.append({"reference": ref_val, "error": str(e)})

    if not results and errors:
        raise ValueError(errors[0]["error"])

    db.query(ShipmentTarget).delete()
    db.commit()

    lookup_cache.rebuild_global_index()

    from app.services.shipment_service import get_shipment_groups
    return {"shipments": results, "groups": get_shipment_groups(db), "errors": errors}
