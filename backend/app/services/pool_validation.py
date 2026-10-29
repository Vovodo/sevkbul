"""Sevkiyat havuzu doğrulama — kaynak: ShipmentLabel (etiket/stock item bazlı)."""
from dataclasses import dataclass
from enum import Enum

from sqlalchemy.orm import Session, joinedload

from decimal import Decimal

from app.models import (
    InventoryLabel, Shipment, ShipmentLabel, ShipmentStatus, ShipmentLabelStatus,
)
from app.services.fifo_quota import (
    group_key, quota_map, scanned_on_date, shipment_scanned_total,
)


class PoolCheckResult(str, Enum):
    IN_POOL = "in_pool"
    ALREADY_SCANNED = "already_scanned"
    OUTSIDE_POOL = "outside_pool"
    NOT_IN_STOCK = "not_in_stock"
    NO_ACTIVE_SHIPMENT = "no_active_shipment"
    QUANTITY_EXCEEDED = "quantity_exceeded"
    BLOCKED_LABEL = "blocked_label"
    NOT_BLOCKED_LABEL = "not_blocked_label"


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


def _already_scanned(db: Session, inventory_id: int) -> ShipmentLabel | None:
    return (
        db.query(ShipmentLabel)
        .options(joinedload(ShipmentLabel.shipment))
        .filter(
            ShipmentLabel.inventory_label_id == inventory_id,
            ShipmentLabel.status == ShipmentLabelStatus.SCANNED,
        )
        .first()
    )


def _expected_fifo_hint(
    db: Session,
    inv: InventoryLabel,
    target_shipment: Shipment | None,
) -> tuple[str | None, str | None, str | None]:
    """
    Okutulan etiket sevkiyat dışı veya miktarı dolmuş olduğunda:
    - Seçili sevkiyatta sıradaki açık FIFO tarihini ve kalan adedi,
    - Etiketin başka bir açık sevkiyata uygun olup olmadığını,
    - Kullanıcıya net Türkçe yönlendirme mesajını döner.
    """
    from sqlalchemy import func
    from app.services.fifo_quota import format_group

    expected_date_str: str | None = None
    expected_rem: Decimal | None = None
    ref_in_target = False

    if target_shipment is not None:
        gid = target_shipment.group_id if target_shipment.group_id is not None else target_shipment.id
        ref_shipments = (
            db.query(Shipment)
            .filter(
                (Shipment.group_id == gid) | (Shipment.id == gid),
                Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]),
            )
            .all()
        )
        matched = [
            s for s in ref_shipments
            if s.reference.strip().upper() == inv.reference.strip().upper()
        ]
        if matched:
            ref_in_target = True
            sh = matched[0]
            hourly = bool(sh.hourly_fifo)
            qmap = quota_map(db, sh)
            for key in sorted(qmap.keys()):
                rem = qmap[key] - scanned_on_date(db, sh, key)
                if rem > Decimal("0.001"):
                    expected_date_str = format_group(key, hourly)
                    expected_rem = rem
                    break

    # Bu etiket başka bir açık sevkiyatın açık FIFO tarihinde kabul ediliyor mu?
    suggested_group_name: str | None = None
    other_shipments = (
        db.query(Shipment)
        .filter(
            func.upper(func.trim(Shipment.reference)) == inv.reference.strip().upper(),
            Shipment.status == ShipmentStatus.ACTIVE,
        )
        .order_by(
            Shipment.sort_order.asc().nulls_last(),
            Shipment.created_at.asc(),
            Shipment.id.asc(),
        )
        .all()
    )
    target_gid = (
        (target_shipment.group_id if target_shipment.group_id is not None else target_shipment.id)
        if target_shipment is not None else None
    )
    for other in other_shipments:
        other_gid = other.group_id if other.group_id is not None else other.id
        if target_gid is not None and other_gid == target_gid:
            continue
        if shipment_scanned_total(db, other) >= Decimal(other.requested_quantity):
            continue
        hourly = bool(other.hourly_fifo)
        key = group_key(inv.fifo_date, hourly)
        qmap = quota_map(db, other)
        if key in qmap and scanned_on_date(db, other, key) < qmap[key] - Decimal("0.001"):
            suggested_group_name = other.group_name or other.name or f"{other_gid}. Sevkiyat"
            break

    inv_date_str = inv.fifo_date.strftime("%d.%m.%Y")
    parts: list[str] = []
    if target_shipment is not None and not ref_in_target:
        parts.append(f"{inv.reference} referansı seçili sevkiyatta yok.")
    elif expected_date_str is not None and expected_rem is not None:
        rem_int = int(expected_rem) if expected_rem == int(expected_rem) else float(expected_rem)
        parts.append(
            f"Okutulan FIFO: {inv_date_str} — Önce {expected_date_str} tarihli etiket okutulmalı (Kalan: {rem_int} adet)."
        )
    if suggested_group_name:
        parts.append(f"Bu etiket '{suggested_group_name}' sevkiyatına uygun.")

    hint_text = " ".join(parts) if parts else None
    return expected_date_str, suggested_group_name, hint_text


def _own_row(db: Session, shipment_id: int, inventory_id: int) -> ShipmentLabel | None:
    return (
        db.query(ShipmentLabel)
        .filter(
            ShipmentLabel.shipment_id == shipment_id,
            ShipmentLabel.inventory_label_id == inventory_id,
        )
        .first()
    )


def _date_decision(
    db: Session,
    inv: InventoryLabel,
    shipment: Shipment,
    blocked_only: bool = False,
) -> PoolCheck:
    """Seçilen sevkiyatta bu etiketin FIFO tarihi açık mı."""
    is_blocked = bool(getattr(inv, "blocked", False))
    if blocked_only and not is_blocked:
        return PoolCheck(
            result=PoolCheckResult.NOT_BLOCKED_LABEL,
            inventory=inv,
            shipment=shipment,
        )

    if (
        shipment.status == ShipmentStatus.COMPLETED
        or shipment_scanned_total(db, shipment) >= Decimal(shipment.requested_quantity)
    ):
        return PoolCheck(
            result=PoolCheckResult.QUANTITY_EXCEEDED,
            inventory=inv,
            shipment=shipment,
        )

    key = group_key(inv.fifo_date, bool(shipment.hourly_fifo))
    quotas = quota_map(db, shipment)
    quota = quotas.get(key)
    if quota is None:
        return PoolCheck(
            result=PoolCheckResult.OUTSIDE_POOL,
            inventory=inv,
            shipment=shipment,
        )

    scanned = scanned_on_date(db, shipment, key)
    if scanned >= quota - Decimal("0.001"):
        return PoolCheck(
            result=PoolCheckResult.QUANTITY_EXCEEDED,
            inventory=inv,
            shipment=shipment,
        )

    return PoolCheck(
        result=PoolCheckResult.IN_POOL,
        inventory=inv,
        shipment=shipment,
        shipment_label=_own_row(db, shipment.id, inv.id),
    )


def check_label_in_shipment_pool(
    db: Session,
    label: str,
    target_shipment_id: int | None = None,
    target_group_id: int | None = None,
    blocked_only: bool = False,
) -> PoolCheck:
    """Okutma, barkoda değil FIFO tarihinin kalan kotasına bakar.

    Seçili sevkiyatta o tarih varsa ve kotası dolmadıysa etiket kabul edilir.
    blocked_only=True ise yalnızca seçili sevkiyattaki referanslara ait BLOKAJLI
    etiketler kabul edilir; blokajsız etiketler reddedilir.
    """
    inv = find_inventory_label(db, label)
    if not inv or bool(getattr(inv, "hidden", False)):
        return PoolCheck(result=PoolCheckResult.NOT_IN_STOCK)

    already = _already_scanned(db, inv.id)
    if already:
        return PoolCheck(
            result=PoolCheckResult.ALREADY_SCANNED,
            inventory=inv,
            shipment=already.shipment,
            shipment_label=already,
        )

    if target_group_id is not None or target_shipment_id is not None:
        gid = target_group_id if target_group_id is not None else target_shipment_id
        group_shipments = (
            db.query(Shipment)
            .filter(
                (Shipment.group_id == gid) | (Shipment.id == gid),
                Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]),
            )
            .all()
        )
        if not group_shipments:
            return PoolCheck(result=PoolCheckResult.NO_ACTIVE_SHIPMENT)

        matches = [s for s in group_shipments if s.reference.strip().upper() == inv.reference.strip().upper()]
        if not matches:
            return PoolCheck(
                result=PoolCheckResult.OUTSIDE_POOL,
                inventory=inv,
                shipment=group_shipments[0],
            )
        return _date_decision(db, inv, matches[0], blocked_only=blocked_only)

    from sqlalchemy import func
    candidates = (
        db.query(Shipment)
        .filter(
            func.upper(func.trim(Shipment.reference)) == inv.reference.strip().upper(),
            Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]),
        )
        .order_by(
            Shipment.sort_order.asc().nulls_last(),
            Shipment.created_at.asc(),
            Shipment.id.asc(),
        )
        .all()
    )
    if not candidates:
        return PoolCheck(result=PoolCheckResult.OUTSIDE_POOL, inventory=inv)

    is_blocked = bool(getattr(inv, "blocked", False))
    if blocked_only and not is_blocked:
        return PoolCheck(
            result=PoolCheckResult.NOT_BLOCKED_LABEL,
            inventory=inv,
            shipment=candidates[0],
        )

    full_match: Shipment | None = None
    for shipment in candidates:
        key = group_key(inv.fifo_date, bool(shipment.hourly_fifo))
        if key not in quota_map(db, shipment):
            continue
        if (
            shipment.status == ShipmentStatus.COMPLETED
            or shipment_scanned_total(db, shipment) >= Decimal(shipment.requested_quantity)
        ):
            full_match = shipment
            continue
        if scanned_on_date(db, shipment, key) >= quota_map(db, shipment)[key] - Decimal("0.001"):
            full_match = shipment
            continue
        return _date_decision(db, inv, shipment, blocked_only=blocked_only)

    if full_match:
        return PoolCheck(
            result=PoolCheckResult.QUANTITY_EXCEEDED,
            inventory=inv,
            shipment=full_match,
        )
    return PoolCheck(
        result=PoolCheckResult.OUTSIDE_POOL,
        inventory=inv,
        shipment=candidates[-1],
    )


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
