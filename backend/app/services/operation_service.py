from sqlalchemy.orm import Session, joinedload

from app.models import (
    Shipment, ShipmentLabel, ShipmentStatus, ShipmentLabelStatus,
    ScanLog, ScanResult, InventoryLabel,
)
from app.services.lookup_cache import lookup_cache
from app.services.shipment_service import get_shipment_progress


def reset_active_shipments(db: Session) -> int:
    """Aktif ve tamamlanmış tüm sevkiyatları SİL ve DB'yi temizle (VPS depolama şişmesin)."""
    from app.models import ShipmentTarget

    active = db.query(Shipment).filter(
        Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED])
    ).all()
    count = len(active)
    shipment_ids = [s.id for s in active]

    if shipment_ids:
        # 1. Sevkiyatlara bağlı etiketleri sil
        db.query(ShipmentLabel).filter(
            ShipmentLabel.shipment_id.in_(shipment_ids)
        ).delete(synchronize_session=False)

        # 2. Sevkiyatlara bağlı scan loglarını sil
        db.query(ScanLog).filter(
            ScanLog.shipment_id.in_(shipment_ids)
        ).delete(synchronize_session=False)

        # 3. Sevkiyat kayıtlarını sil
        db.query(Shipment).filter(
            Shipment.id.in_(shipment_ids)
        ).delete(synchronize_session=False)

    # 4. Sevkiyata bağlı olmayan orphan scan loglarını da sil
    db.query(ScanLog).filter(
        ScanLog.shipment_id.is_(None)
    ).delete(synchronize_session=False)

    # 5. Hedef listesini temizle
    db.query(ShipmentTarget).delete(synchronize_session=False)

    db.commit()

    # 6. Cache'i tamamen temizle
    for sid in shipment_ids:
        lookup_cache.unload_shipment(sid)
    lookup_cache.rebuild_global_index()

    # 7. SQLite VACUUM — disk alanını geri kazan
    try:
        raw_conn = db.bind.raw_connection()
        raw_conn.execute("VACUUM")
        raw_conn.close()
    except Exception:
        pass  # PostgreSQL veya farklı DB'lerde hata yutulur

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


def get_shipment_manifest(db: Session) -> list[dict]:
    """
    Aktif ve tamamlanmış tüm sevkiyatlar için sistemin arka planda hesapladığı
    tam FIFO havuzunu, etiket listesini ve okutma durumlarını döndürür.
    """
    shipments = (
        db.query(Shipment)
        .filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]))
        .order_by(Shipment.created_at.desc())
        .all()
    )

    manifests = []
    for s in shipments:
        prog = get_shipment_progress(db, s.id)

        # Havuzdaki tüm aday etiketler
        sls = (
            db.query(ShipmentLabel)
            .options(joinedload(ShipmentLabel.inventory_label))
            .filter(ShipmentLabel.shipment_id == s.id)
            .all()
        )

        items = []
        for sl in sls:
            inv = sl.inventory_label
            if not inv:
                continue
            is_scanned = sl.status == ShipmentLabelStatus.SCANNED
            
            use_hourly = getattr(s, "hourly_fifo", False)
            group_fmt = inv.fifo_date.strftime("%d.%m.%Y %H:%M") if use_hourly else inv.fifo_date.strftime("%d.%m.%Y")

            items.append({
                "label": inv.label,
                "reference": inv.reference,
                "quantity": float(sl.allocated_quantity),
                "fifo_date": inv.fifo_date.strftime("%d.%m.%Y %H:%M"),
                "fifo_group_date": group_fmt,
                "status": sl.status.value if hasattr(sl.status, "value") else str(sl.status),
                "is_scanned": is_scanned,
                "_fifo_sort_key": inv.fifo_date,
            })

        # Etiketleri FIFO tarihine (en eski en üstte) göre sırala
        items.sort(key=lambda x: x["_fifo_sort_key"])
        for item in items:
            item.pop("_fifo_sort_key", None)

        manifests.append({
            "shipment_id": s.id,
            "reference": s.reference,
            "requested_quantity": prog["requested_quantity"],
            "pool_quantity": prog["pool_quantity"],
            "scanned_quantity": prog["scanned_quantity"],
            "remaining_quantity": prog["remaining_quantity"],
            "progress_percent": prog["progress_percent"],
            "hourly_fifo": getattr(s, "hourly_fifo", False),
            "status": prog["status"],
            "is_complete": prog["is_complete"],
            "items": items,
        })

    return manifests

