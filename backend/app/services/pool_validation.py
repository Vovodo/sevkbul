"""Sevkiyat havuzu doğrulama — kaynak: ShipmentLabel (etiket/stock item bazlı)."""
from dataclasses import dataclass
from enum import Enum

from sqlalchemy.orm import Session, joinedload

from app.models import (
    InventoryLabel, Shipment, ShipmentLabel, ShipmentStatus, ShipmentLabelStatus,
)


class PoolCheckResult(str, Enum):
    IN_POOL = "in_pool"
    ALREADY_SCANNED = "already_scanned"
    OUTSIDE_POOL = "outside_pool"
    NOT_IN_STOCK = "not_in_stock"
    NO_ACTIVE_SHIPMENT = "no_active_shipment"
    QUANTITY_EXCEEDED = "quantity_exceeded"


@dataclass
class PoolCheck:
    result: PoolCheckResult
    inventory: InventoryLabel | None = None
    shipment: Shipment | None = None
    shipment_label: ShipmentLabel | None = None


import re


def find_inventory_label(db: Session, label: str) -> InventoryLabel | None:
    """
    Barkod / QR etiket doğrulaması:
    - Birebir eşleşme (700024541)
    - Başındaki harf/boşluk/önek temizleme (s700024541, S700024541, P700024541 -> 700024541)
    - 6+ rakam dizisi çıkarma (REF_S700024541 -> 700024541)
    """
    raw = label.strip()
    if not raw:
        return None

    # 1. Birebir tam eşleşme
    inv = db.query(InventoryLabel).filter(InventoryLabel.label == raw).first()
    if inv:
        return inv

    # 2. Harf duyarsız tam eşleşme
    inv = db.query(InventoryLabel).filter(InventoryLabel.label.ilike(raw)).first()
    if inv:
        return inv

    # 3. Başındaki harfleri ve tire/boşlukları temizleme (s700024541 -> 700024541)
    stripped = re.sub(r"^[A-Za-z\s_-]+", "", raw)
    if stripped and stripped != raw:
        inv = db.query(InventoryLabel).filter(InventoryLabel.label == stripped).first()
        if inv:
            return inv

    # 4. Rakam dizisi yakalama (en az 6 haneli)
    match = re.search(r"\d{6,}", raw)
    if match:
        extracted = match.group(0)
        if extracted != raw and extracted != stripped:
            inv = db.query(InventoryLabel).filter(InventoryLabel.label == extracted).first()
            if inv:
                return inv

    return None


def check_label_in_shipment_pool(db: Session, label: str) -> PoolCheck:
    """
    Okutma doğrulaması:
    1. Etiket veritabanında var mı? (Baştaki s/S ön ekleri esnek şekilde temizlenir)
    2. Etiket aktif/tamamlanmış sevkiyatın aday etiketleri (ShipmentLabel) arasında mı?
    3. Sevkiyat zaten tamamlanmış mı (Miktar Aşıldı)?
    4. Etiketin ait olduğu FIFO tarih grubunun tahsisli kontenjanı dolmuş mu?
    """
    inv = find_inventory_label(db, label)
    if not inv:
        return PoolCheck(result=PoolCheckResult.NOT_IN_STOCK)

    # 1. Bu referansa ait aktif veya tamamlanmış sevkiyatı bul
    shipment_for_ref = (
        db.query(Shipment)
        .options(joinedload(Shipment.shipment_labels).joinedload(ShipmentLabel.inventory_label))
        .filter(
            Shipment.reference == inv.reference,
            Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]),
        )
        .order_by(Shipment.created_at.desc())
        .first()
    )

    allocation = (
        db.query(ShipmentLabel)
        .options(joinedload(ShipmentLabel.shipment).joinedload(Shipment.shipment_labels).joinedload(ShipmentLabel.inventory_label))
        .join(Shipment)
        .filter(
            ShipmentLabel.inventory_label_id == inv.id,
            Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]),
        )
        .order_by(Shipment.created_at.desc())
        .first()
    )

    # Bu etiket daha önce zaten okutulduysa:
    if allocation and allocation.status == ShipmentLabelStatus.SCANNED:
        return PoolCheck(
            result=PoolCheckResult.ALREADY_SCANNED,
            inventory=inv,
            shipment=allocation.shipment,
            shipment_label=allocation,
        )

    # Eğer referansın sevkiyatı zaten tamamlanmış veya hedef miktar dolmuşsa:
    target_shipment = (allocation.shipment if allocation else shipment_for_ref)
    if target_shipment:
        total_scanned = sum(
            float(sl.scanned_quantity) for sl in target_shipment.shipment_labels
            if sl.status in (ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL)
        )
        if target_shipment.status == ShipmentStatus.COMPLETED or total_scanned >= float(target_shipment.requested_quantity):
            return PoolCheck(
                result=PoolCheckResult.QUANTITY_EXCEEDED,
                inventory=inv,
                shipment=target_shipment,
                shipment_label=allocation,
            )

    if allocation:
        shipment = allocation.shipment

        # Kontenjan hesabı (Group Quota Check)
        use_hourly = getattr(shipment, "hourly_fifo", False)
        def get_g_key(dt):
            return dt.replace(second=0, microsecond=0) if use_hourly else dt.date()

        group_items_by_date = {}
        for sl in shipment.shipment_labels:
            if not sl.inventory_label:
                continue
            g_key = get_g_key(sl.inventory_label.fifo_date)
            if g_key not in group_items_by_date:
                group_items_by_date[g_key] = []
            group_items_by_date[g_key].append(sl)

        sorted_g_keys = sorted(group_items_by_date.keys())
        quota_map = {}
        cum_allocated = 0.0
        target = float(shipment.requested_quantity)

        for g_key in sorted_g_keys:
            sl_list = group_items_by_date[g_key]
            group_stock = sum(float(sl.inventory_label.quantity) for sl in sl_list)
            needed = max(0.0, target - cum_allocated)
            g_quota = min(needed, group_stock)
            quota_map[g_key] = g_quota
            cum_allocated += g_quota

        inv_g_key = get_g_key(inv.fifo_date)
        scanned_in_group = sum(
            float(sl.allocated_quantity)
            for sl in shipment.shipment_labels
            if sl.inventory_label and get_g_key(sl.inventory_label.fifo_date) == inv_g_key and sl.status == ShipmentLabelStatus.SCANNED
        )

        inv_qty = float(inv.quantity)
        allowed_quota = quota_map.get(inv_g_key, 0.0)

        if scanned_in_group + inv_qty > allowed_quota:
            # Grubun kontenjanı doldu!
            return PoolCheck(
                result=PoolCheckResult.OUTSIDE_POOL,
                inventory=inv,
                shipment=shipment,
            )

        return PoolCheck(
            result=PoolCheckResult.IN_POOL,
            inventory=inv,
            shipment=shipment,
            shipment_label=allocation,
        )

    if shipment_for_ref:
        return PoolCheck(
            result=PoolCheckResult.OUTSIDE_POOL,
            inventory=inv,
            shipment=shipment_for_ref,
        )

    return PoolCheck(result=PoolCheckResult.OUTSIDE_POOL, inventory=inv)


def log_allocation_created(
    shipment_id: int,
    reference: str,
    target: float,
    allocations: list,
):
    print("\n==================== FIFO ALLOCATION ====================")
    print(f"Shipment: {shipment_id}")
    print(f"Reference: {reference}")
    print(f"Target: {target}")
    print("Selected stock:")
    total = 0
    for alloc in allocations:
        fifo_str = alloc.fifo_date.strftime("%d.%m.%Y %H:%M")
        qty = float(alloc.allocated_quantity)
        total += qty
        print(f"  ETİKET: {alloc.label} | FIFO: {fifo_str} | Quantity: {qty}")
    print(f"Total allocated: {total}")
    print("=========================================================\n")


def log_scan_check(
    label: str,
    stock_item_id: int | None,
    fifo_str: str,
    allocated: bool,
    result: str,
):
    print("\n-------------------- SCANNED LABEL --------------------")
    print(f"SCANNED LABEL: {label}")
    print(f"STOCK ITEM: {stock_item_id or 'N/A'}")
    print(f"FIFO: {fifo_str}")
    print(f"ALLOCATED TO SHIPMENT: {'TRUE' if allocated else 'FALSE'}")
    print(f"RESULT: {result}")
    print("-------------------------------------------------------\n")
