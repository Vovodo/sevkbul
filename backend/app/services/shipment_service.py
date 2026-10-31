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
from app.services.fifo_quota import group_key, quota_map, record_quotas
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


def _normalize_ref(reference: str) -> str:
    return reference.strip()


def _get_previously_allocated(
    db: Session,
    reference: str,
    exclude_shipment_id: int | None = None,
) -> dict[int, Decimal]:
    """
    Belirtilen referans için aktif/tamamlanmış tüm sevkiyatlardaki
    inventory_label_id → toplam kullanılan/tahsis edilen miktar haritasını döner.

    - PENDING satırlarda allocated_quantity kadar pay ayrılmıştır.
    - SCANNED/PARTIAL satırlarda ise barkod bir kez okutulabildiği için etiketin
      tamamı tüketilmiş sayılır (recalculate_shipments ile birebir aynı kural).
    """
    ref = _normalize_ref(reference)
    query = (
        db.query(
            ShipmentLabel.inventory_label_id,
            ShipmentLabel.allocated_quantity,
            ShipmentLabel.status,
            InventoryLabel.quantity,
        )
        .join(Shipment, ShipmentLabel.shipment_id == Shipment.id)
        .join(InventoryLabel, ShipmentLabel.inventory_label_id == InventoryLabel.id)
        .filter(
            func.upper(func.trim(Shipment.reference)) == ref.upper(),
            Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]),
        )
    )

    if exclude_shipment_id is not None:
        query = query.filter(ShipmentLabel.shipment_id != exclude_shipment_id)

    used_by_inv: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for inv_id, alloc_qty, status, full_qty in query.all():
        if status in (ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL):
            used_by_inv[inv_id] = max(used_by_inv[inv_id], Decimal(str(full_qty)))
        else:
            used_by_inv[inv_id] = min(
                Decimal(str(full_qty)),
                used_by_inv[inv_id] + Decimal(str(alloc_qty or 0)),
            )
    return dict(used_by_inv)


def create_shipment_from_reference(
    db: Session,
    reference: str,
    requested_quantity: Decimal,
    hourly_fifo: bool = False,
    group_id: int | None = None,
    group_name: str | None = None,
    auto_commit: bool = True,
) -> "ShipmentCreateResult":
    reference = _normalize_ref(reference)
    labels = (
        db.query(InventoryLabel)
        .filter(
            func.upper(func.trim(InventoryLabel.reference)) == reference.upper(),
            InventoryLabel.hidden.is_(False),
        )
        .order_by(InventoryLabel.fifo_date.asc(), InventoryLabel.id.asc())
        .all()
    )
    if labels:
        reference = labels[0].reference.strip()
    else:
        any_lbl = (
            db.query(InventoryLabel)
            .filter(func.upper(func.trim(InventoryLabel.reference)) == reference.upper())
            .first()
        )
        if any_lbl:
            reference = any_lbl.reference.strip()

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
        db.flush()
        if auto_commit:
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
    db.flush()

    if auto_commit:
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

    all_rows = (
        db.query(ShipmentLabel, InventoryLabel.blocked)
        .join(InventoryLabel, ShipmentLabel.inventory_label_id == InventoryLabel.id)
        .filter(ShipmentLabel.shipment_id == shipment_id)
        .all()
    )
    all_labels = [sl for sl, _blk in all_rows]

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

    blocked_label_count = sum(1 for _sl, blk in all_rows if blk)
    unblocked_label_count = sum(1 for _sl, blk in all_rows if not blk)
    blocked_quantity = float(sum((Decimal(sl.allocated_quantity or 0) for sl, blk in all_rows if blk), Decimal("0")))
    unblocked_quantity = float(sum((Decimal(sl.allocated_quantity or 0) for sl, blk in all_rows if not blk), Decimal("0")))

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
        "blocked_label_count": blocked_label_count,
        "unblocked_label_count": unblocked_label_count,
        "blocked_quantity": blocked_quantity,
        "unblocked_quantity": unblocked_quantity,
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


def rebalance_reference_pending(db: Session, reference: str) -> None:
    """
    Tek bir referans için aktif sevkiyatların PENDING (tahmini) ShipmentLabel
    satırlarını öncelik sırasına göre yeniden dengeler.
    Okutulan (SCANNED/PARTIAL) satırlara ve tarih kotalarına (ShipmentDateQuota) dokunmaz.
    Böylece aynı FIFO tarihini paylaşan iki sevkiyattan biri diğerinin tahmini etiketini
    okuttuğunda, boşa çıkan diğer etiket anında öteki sevkiyata geçer ve yanlış 'Eksik' uyarısı oluşmaz.
    """
    rkey = _normalize_ref(reference).upper()
    if not rkey:
        return

    shipments = (
        db.query(Shipment)
        .filter(
            func.upper(func.trim(Shipment.reference)) == rkey,
            Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]),
        )
        .order_by(*_shipment_order())
        .all()
    )
    if not shipments:
        return

    sids = [s.id for s in shipments]
    scanned_rows = (
        db.query(ShipmentLabel)
        .filter(
            ShipmentLabel.shipment_id.in_(sids),
            ShipmentLabel.status.in_([ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL]),
        )
        .all()
    )
    scanned_by_sid: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    consumed_ids: set[int] = set()
    for sl in scanned_rows:
        scanned_by_sid[sl.shipment_id] += Decimal(sl.scanned_quantity or 0)
        if sl.inventory_label_id is not None:
            consumed_ids.add(sl.inventory_label_id)

    stock_rows = (
        db.query(InventoryLabel.id, InventoryLabel.quantity, InventoryLabel.fifo_date)
        .filter(
            func.upper(func.trim(InventoryLabel.reference)) == rkey,
            InventoryLabel.hidden.is_(False),
        )
        .order_by(InventoryLabel.fifo_date.asc(), InventoryLabel.id.asc())
        .all()
    )
    stock_list = [(inv_id, Decimal(qty), fifo_dt) for inv_id, qty, fifo_dt in stock_rows]

    db.query(ShipmentLabel).filter(
        ShipmentLabel.shipment_id.in_(sids),
        ShipmentLabel.status == ShipmentLabelStatus.PENDING,
    ).delete(synchronize_session="fetch")

    reserved: dict[int, Decimal] = {}
    new_pending: list[dict] = []
    for s in shipments:
        req = Decimal(s.requested_quantity)
        rem = max(Decimal("0"), req - scanned_by_sid[s.id])
        if rem <= 0:
            continue
        allocs = _allocate_remaining(stock_list, rem, bool(s.hourly_fifo), consumed_ids, reserved)
        for inv_id, qty, _dt in allocs:
            new_pending.append({
                "shipment_id": s.id,
                "inventory_label_id": inv_id,
                "allocated_quantity": qty,
                "scanned_quantity": Decimal("0"),
                "status": ShipmentLabelStatus.PENDING,
            })

    if new_pending:
        db.bulk_insert_mappings(ShipmentLabel, new_pending)
    db.flush()


def _sort_order_for_group(db: Session, group_id: int) -> int:
    existing = (
        db.query(Shipment.sort_order)
        .filter(
            Shipment.group_id == group_id,
            Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]),
            Shipment.sort_order.isnot(None),
        )
        .limit(1)
        .scalar()
    )
    if existing is not None:
        return int(existing)
    current = (
        db.query(func.max(Shipment.sort_order))
        .filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]))
        .scalar()
    )
    return 0 if current is None else int(current) + 1


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
    """Her sevkiyatın, güncel stok ve gerçek okutmalara göre ideal FIFO tarihlerini döner.

    Önceki sevkiyatlarda okutulmuş etiketler tüketilmiş sayılır; her sevkiyatın
    kalan ihtiyacı sırasıyla en eski uygun stoktan karşılanır. Bir okutmanın
    tarihi bu kümede yoksa yeni hesaba göre FIFO dışındadır.
    """
    ordered = sorted(shipments, key=shipment_rank)
    ref_keys = {_normalize_ref(s.reference).upper() for s in ordered}
    if not ref_keys:
        return {}

    ids = [s.id for s in ordered]
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

    stock_query = db.query(
        InventoryLabel.id,
        InventoryLabel.quantity,
        InventoryLabel.fifo_date,
        InventoryLabel.reference,
    ).filter(InventoryLabel.hidden.is_(False)).order_by(InventoryLabel.fifo_date.asc(), InventoryLabel.id.asc())

    stock_by_ref: dict[str, list[tuple]] = defaultdict(list)
    active_stock_ids: set[int] = set()
    for inv_id, quantity, fifo_date, reference in stock_query.all():
        rkey = _normalize_ref(reference).upper()
        if rkey in ref_keys:
            stock_by_ref[rkey].append((inv_id, Decimal(quantity), fifo_date))
            active_stock_ids.add(inv_id)

    actual_reserved: dict[int, Decimal] = {}
    actual_consumed: set[int] = set()
    dates: dict[int, set[datetime]] = {}
    for shipment in ordered:
        hourly = bool(shipment.hourly_fifo)
        rkey = _normalize_ref(shipment.reference).upper()
        base_stock = stock_by_ref.get(rkey, [])
        requested = Decimal(shipment.requested_quantity)
        own = scanned_by_shipment.get(shipment.id, [])

        # Bu sevkiyatın kendi okutulmuş etiketleri yeni stok Excel'inde düşülmüş (hidden=True)
        # olsa bile kendi ideal havuzunda yer almalıdır ki en eski tarih yanlışlıkla FIFO dışı sayılmasın.
        extra_own_stock: list[tuple] = []
        for sl, inv in own:
            if inv is None:
                continue
            if inv.id not in active_stock_ids and inv.fifo_date is not None:
                qty = Decimal(sl.scanned_quantity or inv.quantity or 0)
                if qty > 0:
                    extra_own_stock.append((inv.id, qty, inv.fifo_date))

        if extra_own_stock:
            ref_stock = sorted(base_stock + extra_own_stock, key=lambda x: (x[2], x[0]))
        else:
            ref_stock = base_stock

        # Adım A: Önceki sevkiyatların gerçek tüketimi/rezervasyonu düşüldükten sonra
        # bu sevkiyatın ideal olarak alması gereken FIFO tarihleri:
        temp_reserved = dict(actual_reserved)
        ideal_allocs = _allocate_remaining(
            ref_stock,
            requested,
            hourly,
            actual_consumed,
            temp_reserved,
        )
        dates[shipment.id] = {group_key(fifo_date, hourly) for _id, _qty, fifo_date in ideal_allocs}

        # Adım B: Sonraki sevkiyatlar için bu sevkiyatın gerçek okutmalarını ve kalan tahsisini kilitle:
        scanned_total = Decimal("0")
        for sl, inv in own:
            scanned_total += Decimal(sl.scanned_quantity or 0)
            if inv is not None:
                actual_consumed.add(inv.id)
        rem = max(Decimal("0"), requested - scanned_total)
        if rem > 0:
            _allocate_remaining(
                base_stock,
                rem,
                hourly,
                actual_consumed,
                actual_reserved,
            )
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

    ref_keys = {_normalize_ref(s.reference).upper() for s in shipments}
    stock_query = db.query(
        InventoryLabel.id,
        InventoryLabel.quantity,
        InventoryLabel.fifo_date,
        InventoryLabel.reference,
    ).filter(InventoryLabel.hidden.is_(False)).order_by(InventoryLabel.fifo_date.asc(), InventoryLabel.id.asc())
    stock_by_ref: dict[str, list[tuple]] = defaultdict(list)
    for inv_id, quantity, fifo_date, reference in stock_query.all():
        rkey = _normalize_ref(reference).upper()
        if rkey in ref_keys:
            stock_by_ref[rkey].append((inv_id, Decimal(quantity), fifo_date))

    reserved: dict[int, Decimal] = {}
    pending_rows: list[dict] = []
    quota_rows: list[dict] = []

    for index, shipment in enumerate(shipments, start=1):
        if on_progress and (index == 1 or index == total or index % 10 == 0):
            on_progress(index - 1, total, shipment.reference)
            time.sleep(0.001)

        hourly = bool(shipment.hourly_fifo)
        rkey = _normalize_ref(shipment.reference).upper()
        requested = Decimal(shipment.requested_quantity)
        own = scanned_by_shipment.get(shipment.id, [])
        scanned_total = sum((Decimal(sl.scanned_quantity or 0) for sl, _ in own), Decimal("0"))
        remaining = requested - scanned_total
        if remaining < 0:
            remaining = Decimal("0")

        allocations = _allocate_remaining(
            stock_by_ref.get(rkey, []),
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


def _build_shipments_progress_batch(db: Session, shipments: list[Shipment]) -> list[dict]:
    """
    Tüm sevkiyat kalemlerinin ilerleme ve blokaj istatistiklerini N+1 sorgu yerine
    tek seferde toplu (batch) olarak hesaplar.
    """
    if not shipments:
        return []

    sids = [s.id for s in shipments]
    label_rows = (
        db.query(
            ShipmentLabel.shipment_id,
            ShipmentLabel.allocated_quantity,
            ShipmentLabel.scanned_quantity,
            ShipmentLabel.status,
            InventoryLabel.blocked,
        )
        .join(InventoryLabel, ShipmentLabel.inventory_label_id == InventoryLabel.id)
        .filter(ShipmentLabel.shipment_id.in_(sids))
        .all()
    )
    labels_by_sid: dict[int, list] = defaultdict(list)
    for sid, alloc_q, scan_q, st, blk in label_rows:
        labels_by_sid[sid].append((alloc_q, scan_q, st, bool(blk)))

    items_out: list[dict] = []
    for shipment in shipments:
        s_labels = labels_by_sid.get(shipment.id, [])
        requested = float(shipment.requested_quantity)
        pool_f = requested

        scanned_qty = sum(
            (Decimal(scan_q or 0) for _alloc_q, scan_q, st, _blk in s_labels
             if st in (ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL)),
            Decimal("0"),
        )
        scanned_labels_count = sum(
            1 for _alloc_q, _scan_q, st, _blk in s_labels
            if st in (ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL)
        )
        scanned_f = float(scanned_qty)
        remaining_target = max(0.0, requested - scanned_f)
        progress = (scanned_f / requested * 100) if requested > 0 else 0.0
        allocated = sum((Decimal(alloc_q or 0) for alloc_q, _scan_q, _st, _blk in s_labels), Decimal("0"))
        short_quantity = float(max(Decimal("0"), Decimal(str(shipment.requested_quantity)) - allocated))
        fully_short = short_quantity > 0 and allocated <= 0

        blk_cnt = sum(1 for _alloc_q, _scan_q, _st, blk in s_labels if blk)
        unblk_cnt = sum(1 for _alloc_q, _scan_q, _st, blk in s_labels if not blk)
        blk_qty = sum((Decimal(alloc_q or 0) for alloc_q, _scan_q, _st, blk in s_labels if blk), Decimal("0"))
        unblk_qty = sum((Decimal(alloc_q or 0) for alloc_q, _scan_q, _st, blk in s_labels if not blk), Decimal("0"))

        items_out.append({
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
            "blocked_label_count": blk_cnt,
            "unblocked_label_count": unblk_cnt,
            "blocked_quantity": float(blk_qty),
            "unblocked_quantity": float(unblk_qty),
        })

    return items_out


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

    progress_list = _build_shipments_progress_batch(db, shipments)
    groups_map: dict[int, dict] = {}
    for s, item_data in zip(shipments, progress_list):
        gid = s.group_id if s.group_id is not None else s.id
        if gid not in groups_map:
            groups_map[gid] = {
                "group_id": gid,
                "name": s.group_name or s.name,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "items": [],
            }
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
            "blocked_label_count": sum(item.get("blocked_label_count", 0) for item in items),
            "unblocked_label_count": sum(item.get("unblocked_label_count", 0) for item in items),
            "items": items,
        })

    return result


def reorder_shipment_groups(db: Session, group_ids: list[int]) -> list[dict]:
    """Sevkiyat kartlarının liste sırasını kullanıcının verdiği diziye çeker ve FIFO'yu yeniden hesaplar."""
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
    if shipments:
        recalculate_shipments(db)
    return get_shipment_groups(db)


def get_active_shipments(db: Session) -> list[dict]:
    # Geriye dönük uyumluluk: bireysel referansları da dönebiliriz
    shipments = (
        db.query(Shipment)
        .filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]))
        .order_by(Shipment.created_at.desc())
        .all()
    )
    return _build_shipments_progress_batch(db, shipments)
