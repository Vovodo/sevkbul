from decimal import Decimal
from datetime import datetime
from dataclasses import dataclass
from collections import defaultdict
import time

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    InventoryLabel, Shipment, ShipmentLabel, ShipmentStatus,
    ShipmentLabelStatus, ShipmentDateQuota,
)
from app.services.fifo_engine import calculate_fifo_groups, InventoryItem
from app.services.fifo_quota import group_key, record_quotas
from app.services.lookup_cache import lookup_cache
from app.services.pool_validation import log_allocation_created


STOCK_EXHAUSTED = "Eksik"
STOCK_MISSING = "Eksik"
STOCK_SHORT = "Eksik"


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
    stock_note: str | None = None


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

    if group_id is None:
        max_gid = db.query(func.max(Shipment.group_id)).scalar()
        group_id = (max_gid or 0) + 1
    if group_name is None:
        group_name = f"{group_id}. Sevkiyat"
    sort_order = _sort_order_for_group(db, group_id)

    def open_without_stock(note: str) -> ShipmentCreateResult:
        shipment = Shipment(
            group_id=group_id,
            group_name=group_name,
            reference=reference,
            requested_quantity=requested_quantity,
            status=ShipmentStatus.ACTIVE,
            hourly_fifo=hourly_fifo,
            stock_note=note,
            sort_order=sort_order,
        )
        db.add(shipment)
        db.commit()
        db.refresh(shipment)
        lookup_cache.load_shipment(db, shipment.id)
        return ShipmentCreateResult(
            shipment_id=shipment.id,
            reference=reference,
            requested_quantity=requested_quantity,
            pool_quantity=Decimal(0),
            label_count=0,
            insufficient_stock=True,
            remaining_unfulfilled=requested_quantity,
            fifo_group_count=0,
            stock_note=note,
        )

    if not labels:
        return open_without_stock(STOCK_MISSING)

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
        return open_without_stock(STOCK_EXHAUSTED)

    fifo_result = calculate_fifo_groups(items, requested_quantity, hourly_fifo=hourly_fifo)

    if not fifo_result.allocations:
        return open_without_stock(STOCK_SHORT)

    shipment = Shipment(
        group_id=group_id,
        group_name=group_name,
        reference=reference,
        requested_quantity=requested_quantity,
        status=ShipmentStatus.ACTIVE,
        hourly_fifo=hourly_fifo,
        sort_order=sort_order,
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

    record_quotas(db, shipment.id, fifo_result.allocations, hourly_fifo)

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
        stock_note=None,
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
    allocated = sum((Decimal(sl.allocated_quantity or 0) for sl in all_labels), Decimal("0"))
    short_quantity = float(max(Decimal("0"), Decimal(str(shipment.requested_quantity)) - allocated))
    fully_short = short_quantity > 0 and allocated <= 0

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
        "stock_note": "Eksik" if fully_short else None,
        "short_quantity": short_quantity,
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


def _allocate_remaining(
    labels: list[tuple],
    remaining: Decimal,
    hourly: bool,
    consumed_ids: set[int],
    reserved: dict[int, Decimal],
) -> list[tuple[int, Decimal, datetime]]:
    """En eski stoktan, ihtiyaç kadar pay ayırır. Listenin geri kalanına bakmaz."""
    if remaining <= 0 or not labels:
        return []

    allocations: list[tuple[int, Decimal, datetime]] = []
    group: list[tuple] = []
    current_key = None

    def flush(items: list[tuple], need: Decimal) -> Decimal:
        if need <= 0 or not items:
            return need
        group_total = sum((qty for _id, qty, _dt in items), Decimal("0"))
        quota = min(need, group_total)
        left = quota
        for inv_id, available, fifo_date in items:
            if left <= 0:
                break
            take = min(available, left)
            if take <= 0:
                continue
            allocations.append((inv_id, take, fifo_date))
            reserved[inv_id] = reserved.get(inv_id, Decimal("0")) + take
            left -= take
        return need - quota

    for inv_id, quantity, fifo_date in labels:
        if inv_id in consumed_ids:
            continue
        available = quantity - reserved.get(inv_id, Decimal("0"))
        if available <= 0:
            continue
        key = group_key(fifo_date, hourly)
        if current_key is None:
            current_key = key
        if key != current_key:
            remaining = flush(group, remaining)
            group = []
            current_key = key
            if remaining <= 0:
                break
        group.append((inv_id, available, fifo_date))

    if remaining > 0 and group:
        flush(group, remaining)
    return allocations


def _sort_order_for_group(db: Session, group_id: int) -> int:
    existing = (
        db.query(Shipment.sort_order)
        .filter(Shipment.group_id == group_id, Shipment.sort_order.isnot(None))
        .limit(1)
        .scalar()
    )
    if existing is not None:
        return int(existing)
    current = db.query(func.max(Shipment.sort_order)).scalar()
    return int(current or 0) + 1


def _shipment_order():
    return (
        Shipment.sort_order.asc().nulls_last(),
        Shipment.created_at.asc(),
        Shipment.id.asc(),
    )


def shipment_rank(shipment: Shipment):
    created = shipment.created_at or datetime.min
    return (
        shipment.sort_order if shipment.sort_order is not None else 10**9,
        created,
        shipment.id or 0,
    )


def ideal_fifo_dates(db: Session, shipments: list[Shipment]) -> dict[int, set[datetime]]:
    """Her sevkiyatın, güncel stokta baştan hesaplanan FIFO tarihlerini döner.

    Okutmalar bu pencereyi kaydırmaz. Bir okutmanın tarihi bu kümede yoksa
    yeni hesaba göre FIFO dışındadır.
    """
    ordered = sorted(shipments, key=shipment_rank)
    references = {s.reference for s in ordered}
    if not references:
        return {}

    stock_query = db.query(
        InventoryLabel.id,
        InventoryLabel.quantity,
        InventoryLabel.fifo_date,
        InventoryLabel.reference,
    ).order_by(InventoryLabel.fifo_date.asc(), InventoryLabel.id.asc())
    if len(references) <= 400:
        stock_query = stock_query.filter(InventoryLabel.reference.in_(references))

    stock_by_ref: dict[str, list[tuple]] = defaultdict(list)
    for inv_id, quantity, fifo_date, reference in stock_query.all():
        if reference in references:
            stock_by_ref[reference].append((inv_id, Decimal(quantity), fifo_date))

    reserved: dict[int, Decimal] = {}
    dates: dict[int, set[datetime]] = {}
    for shipment in ordered:
        hourly = bool(shipment.hourly_fifo)
        allocations = _allocate_remaining(
            stock_by_ref.get(shipment.reference, []),
            Decimal(shipment.requested_quantity),
            hourly,
            set(),
            reserved,
        )
        dates[shipment.id] = {group_key(fifo_date, hourly) for _id, _qty, fifo_date in allocations}
    return dates


def recalculate_shipments(db: Session, on_progress=None) -> dict:
    """Açık sevkiyatların FIFO tarihlerini güncel stok ve okutmalara göre yeniden kurar.

    Okutulan etiketler yerinde kalır. Bekleyen tahmin satırları ve tarih kotaları
    silinip, kalan ihtiyaç en eski uygun stoktan tekrar dağıtılır. Daha eski
    sevkiyatın yeni planı, sonrakinin başlangıcını belirler.
    """
    shipments = (
        db.query(Shipment)
        .filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]))
        .order_by(*_shipment_order())
        .all()
    )
    if not shipments:
        raise ValueError("Yeniden hesaplanacak sevkiyat yok")

    ids = [s.id for s in shipments]
    total = len(shipments)
    if on_progress:
        on_progress(0, total, "Stok okunuyor")

    scanned_rows = (
        db.query(ShipmentLabel, InventoryLabel)
        .outerjoin(InventoryLabel, ShipmentLabel.inventory_label_id == InventoryLabel.id)
        .filter(
            ShipmentLabel.shipment_id.in_(ids),
            ShipmentLabel.status.in_([ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL]),
        )
        .all()
    )
    scanned_by_shipment: dict[int, list] = defaultdict(list)
    consumed_ids: set[int] = set()
    for sl, inv in scanned_rows:
        scanned_by_shipment[sl.shipment_id].append((sl, inv))
        if inv is not None:
            consumed_ids.add(inv.id)

    references = {s.reference for s in shipments}
    stock_query = db.query(
        InventoryLabel.id,
        InventoryLabel.quantity,
        InventoryLabel.fifo_date,
        InventoryLabel.reference,
    ).order_by(InventoryLabel.fifo_date.asc(), InventoryLabel.id.asc())
    if len(references) <= 400:
        stock_query = stock_query.filter(InventoryLabel.reference.in_(references))
    stock_by_ref: dict[str, list[tuple]] = defaultdict(list)
    for inv_id, quantity, fifo_date, reference in stock_query.all():
        if reference in references:
            stock_by_ref[reference].append((inv_id, Decimal(quantity), fifo_date))

    reserved: dict[int, Decimal] = {}
    pending_rows: list[dict] = []
    quota_rows: list[dict] = []

    for index, shipment in enumerate(shipments, start=1):
        if on_progress and (index == 1 or index == total or index % 10 == 0):
            on_progress(index - 1, total, shipment.reference)
            time.sleep(0.001)

        hourly = bool(shipment.hourly_fifo)
        requested = Decimal(shipment.requested_quantity)
        own = scanned_by_shipment.get(shipment.id, [])
        scanned_total = sum((Decimal(sl.scanned_quantity or 0) for sl, _ in own), Decimal("0"))
        remaining = requested - scanned_total
        if remaining < 0:
            remaining = Decimal("0")

        allocations = _allocate_remaining(
            stock_by_ref.get(shipment.reference, []),
            remaining,
            hourly,
            consumed_ids,
            reserved,
        )

        buckets: dict[datetime, Decimal] = {}
        for sl, inv in own:
            if inv is None:
                continue
            qty = Decimal(sl.scanned_quantity or 0)
            if qty <= 0:
                continue
            key = group_key(inv.fifo_date, hourly)
            buckets[key] = buckets.get(key, Decimal("0")) + qty

        for inv_id, qty, fifo_date in allocations:
            key = group_key(fifo_date, hourly)
            buckets[key] = buckets.get(key, Decimal("0")) + qty
            pending_rows.append({
                "shipment_id": shipment.id,
                "inventory_label_id": inv_id,
                "allocated_quantity": qty,
                "scanned_quantity": Decimal(0),
                "status": ShipmentLabelStatus.PENDING,
            })

        for key, qty in buckets.items():
            if qty <= 0:
                continue
            quota_rows.append({
                "shipment_id": shipment.id,
                "fifo_group": key,
                "quota_quantity": qty,
            })

        if scanned_total >= requested and shipment.status == ShipmentStatus.ACTIVE:
            shipment.status = ShipmentStatus.COMPLETED
            shipment.completed_at = datetime.utcnow()
        elif scanned_total < requested and shipment.status == ShipmentStatus.COMPLETED:
            shipment.status = ShipmentStatus.ACTIVE
            shipment.completed_at = None

        if allocations or scanned_total > 0:
            shipment.stock_note = None
        elif shipment.stock_note is None and remaining > 0:
            shipment.stock_note = STOCK_EXHAUSTED

    if on_progress:
        on_progress(total, total, "Sonuçlar kaydediliyor")

    db.query(ShipmentLabel).filter(
        ShipmentLabel.shipment_id.in_(ids),
        ShipmentLabel.status == ShipmentLabelStatus.PENDING,
    ).delete(synchronize_session=False)
    db.query(ShipmentDateQuota).filter(
        ShipmentDateQuota.shipment_id.in_(ids),
    ).delete(synchronize_session=False)
    if pending_rows:
        db.bulk_insert_mappings(ShipmentLabel, pending_rows)
    if quota_rows:
        db.bulk_insert_mappings(ShipmentDateQuota, quota_rows)

    db.commit()
    lookup_cache.load_all_active(db)
    return {"updated": total}


def get_shipment_groups(db: Session) -> list[dict]:
    """
    Tüm aktif/tamamlanmış sevkiyatları group_id'ye göre birleştirerek
    tekil Sevkiyat Kartları şeklinde döner.
    """
    shipments = (
        db.query(Shipment)
        .filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]))
        .order_by(*_shipment_order())
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


def reorder_shipment_groups(db: Session, group_ids: list[int]) -> list[dict]:
    """Sevkiyat kartlarının liste sırasını kullanıcının verdiği diziye çeker."""
    shipments = (
        db.query(Shipment)
        .filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]))
        .all()
    )
    by_group: dict[int, list[Shipment]] = {}
    for shipment in shipments:
        gid = shipment.group_id if shipment.group_id is not None else shipment.id
        by_group.setdefault(gid, []).append(shipment)

    unknown = [gid for gid in group_ids if gid not in by_group]
    if unknown:
        raise ValueError("Listede olmayan sevkiyat var")
    if len(group_ids) != len(set(group_ids)):
        raise ValueError("Sevkiyat sırası tekrar ediyor")

    placed: set[int] = set()
    for index, gid in enumerate(group_ids):
        placed.add(gid)
        for shipment in by_group[gid]:
            shipment.sort_order = index
    tail = len(group_ids)
    for gid, rows in by_group.items():
        if gid in placed:
            continue
        for shipment in rows:
            shipment.sort_order = tail
        tail += 1
    db.commit()
    return get_shipment_groups(db)


def get_active_shipments(db: Session) -> list[dict]:
    # Geriye dönük uyumluluk: bireysel referansları da dönebiliriz
    shipments = (
        db.query(Shipment)
        .filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]))
        .order_by(Shipment.created_at.desc())
        .all()
    )
    return [get_shipment_progress(db, s.id) for s in shipments]
