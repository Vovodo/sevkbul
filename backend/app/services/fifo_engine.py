from decimal import Decimal
from dataclasses import dataclass
from datetime import datetime, date
from collections import defaultdict


@dataclass
class InventoryItem:
    label: str
    reference: str
    quantity: Decimal
    fifo_date: datetime
    id: int | None = None


@dataclass
class FifoAllocation:
    label: str
    inventory_label_id: int | None
    reference: str
    total_quantity: Decimal
    allocated_quantity: Decimal
    fifo_date: datetime
    fifo_group_date: date | datetime


@dataclass
class FifoGroupResult:
    allocations: list[FifoAllocation]
    remaining_unfulfilled: Decimal
    pool_quantity: Decimal
    included_group_dates: list[date | datetime]


def fifo_calendar_day(dt: datetime) -> date:
    """Aynı takvim günündeki X98FIFO_TARIH değerleri aynı FIFO grubudur."""
    return dt.date()


def fifo_datetime_group(dt: datetime) -> datetime:
    """Dakika hassasiyetinde FIFO grubu (saniye ve mikrosaniye sıfırlanır)."""
    return dt.replace(second=0, microsecond=0)


def calculate_fifo_groups(
    items: list[InventoryItem],
    requested_quantity: Decimal,
    hourly_fifo: bool = False,
) -> FifoGroupResult:
    """
    FIFO Tarih Grubu & Kontenjan Mantığı:
    1. Etiketler fifo_date sırasına göre takvim günlerine veya saatlerine (FIFO gruplarına) ayrılır.
       - hourly_fifo=False: Gün bazlı gruplama (YYYY-MM-DD)
       - hourly_fifo=True: Saat/Dakika bazlı gruplama (YYYY-MM-DD HH:MM)
    2. En eski gruptan başlanarak hedef miktara (requested_quantity) ulaşana kadar kontenjan tahsis edilir.
    3. Tahsis edilen FIFO grubundaki TÜM etiketler aday olarak havuza (ShipmentLabel) eklenir.
    4. Okutma sırasında o grubun tahsisli kontenjanı dolana kadar bu gruptaki HANGİ etiket okutulursa okutulsun KABUL edilir.
    5. Kontenjan dolduğu anda aynı gruptaki diğer etiketler REJECT edilir.
    """
    if not items or requested_quantity <= 0:
        return FifoGroupResult(
            allocations=[],
            remaining_unfulfilled=requested_quantity if requested_quantity > 0 else Decimal(0),
            pool_quantity=Decimal(0),
            included_group_dates=[],
        )

    grouped: dict[date | datetime, list[InventoryItem]] = defaultdict(list)
    for item in sorted(items, key=lambda x: x.fifo_date):
        g_key = fifo_datetime_group(item.fifo_date) if hourly_fifo else fifo_calendar_day(item.fifo_date)
        grouped[g_key].append(item)

    sorted_keys = sorted(grouped.keys())

    allocations: list[FifoAllocation] = []
    included_dates_list: list[date | datetime] = []
    cumulative = Decimal(0)

    for g_key in sorted_keys:
        if cumulative >= requested_quantity:
            break

        group_items = grouped[g_key]
        group_total_stock = sum(i.quantity for i in group_items)
        needed = requested_quantity - cumulative
        group_allocated_quota = min(needed, group_total_stock)

        included_dates_list.append(g_key)

        for item in group_items:
            allocations.append(FifoAllocation(
                label=item.label,
                inventory_label_id=item.id,
                reference=item.reference,
                total_quantity=item.quantity,
                allocated_quantity=item.quantity,
                fifo_date=item.fifo_date,
                fifo_group_date=g_key,
            ))

        cumulative += group_allocated_quota

    remaining = max(Decimal(0), requested_quantity - cumulative)

    return FifoGroupResult(
        allocations=allocations,
        remaining_unfulfilled=remaining,
        pool_quantity=cumulative,
        included_group_dates=included_dates_list,
    )


def calculate_fifo(
    items: list[InventoryItem],
    requested_quantity: Decimal,
) -> tuple[list[FifoAllocation], Decimal]:
    """Geriye uyumluluk için wrapper."""
    result = calculate_fifo_groups(items, requested_quantity)
    return result.allocations, result.remaining_unfulfilled
