from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session, joinedload

from app.models import (
    Shipment, ShipmentLabel, ShipmentStatus, ShipmentLabelStatus,
    ShipmentDateQuota, ScanLog, ScanResult, InventoryLabel,
)
from app.services.fifo_quota import format_group, group_key, quota_map, scanned_on_date
from app.services.lookup_cache import lookup_cache
from app.services.shipment_service import get_shipment_progress, ideal_fifo_dates


def delete_shipment_group(db: Session, group_id: int) -> int:
    """Tek bir sevkiyat grubunu, etiket ve okutma kayıtlarıyla birlikte siler.

    Diğer sevkiyat gruplarına ve hedef listesine dokunmaz.
    """
    shipments = db.query(Shipment).filter(Shipment.group_id == group_id).all()
    if not shipments:
        # Eski kayıtlarda grup numarası yoktu; grup kimliği sevkiyatın kendi id'siydi.
        # Gerçek bir grup varken aynı numaralı eski kaydı silme.
        shipments = db.query(Shipment).filter(
            Shipment.group_id.is_(None),
            Shipment.id == group_id,
        ).all()
    if not shipments:
        raise ValueError("Sevkiyat grubu bulunamadı")

    shipment_ids = [s.id for s in shipments]
    db.query(ShipmentDateQuota).filter(
        ShipmentDateQuota.shipment_id.in_(shipment_ids)
    ).delete(synchronize_session=False)
    db.query(ShipmentLabel).filter(
        ShipmentLabel.shipment_id.in_(shipment_ids)
    ).delete(synchronize_session=False)
    db.query(ScanLog).filter(
        ScanLog.shipment_id.in_(shipment_ids)
    ).delete(synchronize_session=False)
    db.query(Shipment).filter(
        Shipment.id.in_(shipment_ids)
    ).delete(synchronize_session=False)
    db.commit()

    for sid in shipment_ids:
        lookup_cache.unload_shipment(sid)
    lookup_cache.rebuild_global_index()
    return len(shipment_ids)


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
        db.query(ShipmentDateQuota).filter(
            ShipmentDateQuota.shipment_id.in_(shipment_ids)
        ).delete(synchronize_session=False)

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
        .order_by(
            Shipment.sort_order.asc().nulls_last(),
            Shipment.created_at.asc(),
            Shipment.id.asc(),
        )
        .all()
    )

    manifests = []
    ideal = ideal_fifo_dates(db, shipments)
    for s in shipments:
        prog = get_shipment_progress(db, s.id)

        use_hourly = bool(getattr(s, "hourly_fifo", False))
        quotas = quota_map(db, s)
        inside = ideal.get(s.id, set())
        scanned_rows = (
            db.query(ShipmentLabel)
            .options(joinedload(ShipmentLabel.inventory_label))
            .filter(
                ShipmentLabel.shipment_id == s.id,
                ShipmentLabel.status.in_([ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL]),
            )
            .all()
        )
        scanned_by_date: dict = {}
        for sl in scanned_rows:
            inv = sl.inventory_label
            if not inv:
                continue
            key = group_key(inv.fifo_date, use_hourly)
            scanned_by_date.setdefault(key, []).append(sl)

        items = []
        for key in sorted(quotas):
            quota = float(quotas[key])
            done = float(scanned_on_date(db, s, key))
            filled = done >= quota - 0.001
            # Uyarı yalnızca yeniden hesapta bu tarihin yerini daha eski bir FIFO aldıysa.
            outside = key not in inside and done > 0.001
            label_rows = scanned_by_date.get(key, [])
            items.append({
                "label": format_group(key, use_hourly),
                "reference": s.reference,
                "quantity": quota,
                "scanned_quantity": done,
                "fifo_date": format_group(key, use_hourly),
                "fifo_group_date": format_group(key, use_hourly),
                "status": "scanned" if filled else "pending",
                "is_scanned": filled,
                "outside_fifo": outside,
                "outside_reason": "window" if outside else None,
                "scanned_labels": [
                    {
                        "label": sl.inventory_label.label,
                        "quantity": float(sl.scanned_quantity or 0),
                        "outside_fifo": outside,
                    }
                    for sl in label_rows
                    if sl.inventory_label
                ],
            })

        manifests.append({
            "shipment_id": s.id,
            "group_id": s.group_id or s.id,
            "group_name": s.group_name or s.name,
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


def list_candidate_labels(db: Session, shipment_id: int, fifo_group: str) -> dict:
    """Bir FIFO tarihinde henüz okutulmamış, bu sevkiyata kabul edilecek etiketler."""
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if shipment is None or shipment.status not in (ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED):
        raise ValueError("Sevkiyat bulunamadı")

    hourly = bool(shipment.hourly_fifo)
    try:
        parsed = datetime.strptime(fifo_group.strip(), "%d.%m.%Y %H:%M" if hourly else "%d.%m.%Y")
    except ValueError as exc:
        raise ValueError("FIFO tarihi okunamadı") from exc

    key = group_key(parsed, hourly)
    quota = quota_map(db, shipment).get(key, Decimal("0"))
    done = scanned_on_date(db, shipment, key)
    remaining = quota - done
    if remaining < 0:
        remaining = Decimal("0")

    end = key + (timedelta(minutes=1) if hourly else timedelta(days=1))
    rows = (
        db.query(InventoryLabel)
        .filter(
            InventoryLabel.reference == shipment.reference,
            InventoryLabel.fifo_date >= key,
            InventoryLabel.fifo_date < end,
        )
        .order_by(InventoryLabel.fifo_date.asc(), InventoryLabel.id.asc())
        .all()
    )
    labels = []
    if remaining > 0 and rows:
        consumed = {
            row[0]
            for row in db.query(ShipmentLabel.inventory_label_id).filter(
                ShipmentLabel.inventory_label_id.in_([row.id for row in rows]),
                ShipmentLabel.status.in_([ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL]),
            ).all()
        }
        for inv in rows:
            if inv.id in consumed or Decimal(inv.quantity) <= 0:
                continue
            labels.append({
                "label": inv.label,
                "quantity": float(inv.quantity),
                "fifo_time": inv.fifo_date.strftime("%H:%M"),
            })

    return {"remaining": float(remaining), "labels": labels}

