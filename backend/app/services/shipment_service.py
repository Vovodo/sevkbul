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
    group_id: int | None = None,
    group_name: str | None = None,
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

    if group_id is None:
        max_gid = db.query(func.max(Shipment.group_id)).scalar()
        group_id = (max_gid or 0) + 1
    if group_name is None:
        group_name = f"{group_id}. Sevkiyat"

    shipment = Shipment(
        group_id=group_id,
        group_name=group_name,
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
    group_id: int | None = None,
    group_name: str | None = None,
) -> ShipmentCreateResult:
    return create_shipment_from_reference(
        db, reference, requested_quantity, hourly_fifo=hourly_fifo,
        group_id=group_id, group_name=group_name
    )


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

    scanned_labels_count = sum(
        1 for sl in all_labels
        if sl.status in (ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL)
    )

    scanned_f = float(scanned_qty)
    remaining_target = max(0, requested - scanned_f)
    progress = (scanned_f / requested * 100) if requested > 0 else 0

    return {
        "shipment_id": shipment.id,
        "group_id": shipment.group_id or shipment.id,
        "reference": shipment.reference,
        "name": shipment.name or shipment.group_name,
        "requested_quantity": requested,
        "pool_quantity": pool_f,
        "scanned_quantity": scanned_f,
        "scanned_label_count": scanned_labels_count,
        "remaining_quantity": remaining_target,
        "progress_percent": round(min(progress, 100), 1),
        "status": shipment.status.value,
        "is_complete": shipment.status == ShipmentStatus.COMPLETED,
    }


def rename_shipment_group(db: Session, group_id: int, name: str) -> list[dict]:
    """Sevkiyat grubuna kullanıcı dostu bir isim ata (ör. 'Pazartesi Yüklemesi')."""
    shipments = db.query(Shipment).filter(
        (Shipment.group_id == group_id) | (Shipment.id == group_id)
    ).all()
    if not shipments:
        raise ValueError("Sevkiyat grubu bulunamadı")
    for s in shipments:
        s.group_name = name.strip() or None
        s.name = name.strip() or None
    db.commit()
    return get_shipment_groups(db)


def rename_shipment(db: Session, shipment_id: int, name: str) -> dict:
    """Sevkiyata kullanıcı dostu bir isim ata (ör. 'TIR-1 Yükleme')."""
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not shipment:
        raise ValueError("Sevkiyat bulunamadı")
    shipment.name = name.strip() or None
    if shipment.group_id:
        # Aynı gruptaki diğerlerine de yansıt
        other = db.query(Shipment).filter(Shipment.group_id == shipment.group_id).all()
        for o in other:
            o.group_name = name.strip() or None
            o.name = name.strip() or None
    db.commit()
    return get_shipment_progress(db, shipment_id)


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


def get_shipment_groups(db: Session) -> list[dict]:
    """
    Tüm aktif/tamamlanmış sevkiyatları group_id'ye göre birleştirerek
    tekil Sevkiyat Kartları şeklinde döner.
    """
    shipments = (
        db.query(Shipment)
        .filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]))
        .order_by(Shipment.created_at.asc(), Shipment.id.asc())
        .all()
    )
    if not shipments:
        return []

    groups_map: dict[int, dict] = {}
    for s in shipments:
        gid = s.group_id if s.group_id is not None else s.id
        if gid not in groups_map:
            groups_map[gid] = {
                "group_id": gid,
                "name": s.group_name or s.name,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "items": [],
            }
        item_data = get_shipment_progress(db, s.id)
        groups_map[gid]["items"].append(item_data)

    result = []
    for idx, (gid, g) in enumerate(groups_map.items()):
        items = g["items"]
        tot_req = sum(item["requested_quantity"] for item in items)
        tot_scanned = sum(item["scanned_quantity"] for item in items)
        tot_rem = max(0.0, tot_req - tot_scanned)
        pct = round((tot_scanned / tot_req * 100), 1) if tot_req > 0 else 0.0
        all_done = len(items) > 0 and all(item["is_complete"] for item in items)

        result.append({
            "group_id": gid,
            "index": idx + 1,
            "name": g["name"] or f"{idx + 1}. Sevkiyat",
            "requested_quantity": tot_req,
            "scanned_quantity": tot_scanned,
            "remaining_quantity": tot_rem,
            "progress_percent": min(pct, 100.0),
            "status": "completed" if all_done else "active",
            "is_complete": all_done,
            "created_at": g["created_at"],
            "items": items,
        })

    return result


def get_active_shipments(db: Session) -> list[dict]:
    # Geriye dönük uyumluluk: bireysel referansları da dönebiliriz
    shipments = (
        db.query(Shipment)
        .filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]))
        .order_by(Shipment.created_at.desc())
        .all()
    )
    return [get_shipment_progress(db, s.id) for s in shipments]
