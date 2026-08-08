import pytest
from decimal import Decimal
from datetime import datetime

from app.services.fifo_engine import calculate_fifo_groups, InventoryItem, fifo_calendar_day


def make_item(label: str, qty: float, day: int, hour: int = 10, month: int = 7, year: int = 2026) -> InventoryItem:
    return InventoryItem(
        label=label,
        reference="X",
        quantity=Decimal(str(qty)),
        fifo_date=datetime(year, month, day, hour, 0),
    )


class TestFifoGroupEngine:
    def test_same_day_grouping(self):
        """Aynı gün farklı saatler aynı FIFO grubu."""
        items = [
            make_item("A001", 30, 10, 8),
            make_item("A002", 30, 10, 9),
            make_item("A003", 30, 10, 14),
            make_item("A004", 30, 10, 17),
        ]
        result = calculate_fifo_groups(items, Decimal("240"))
        labels = {a.label for a in result.allocations}
        assert labels == {"A001", "A002", "A003", "A004"}
        assert all(a.allocated_quantity == Decimal("30") for a in result.allocations)

    def test_240_request_includes_boundary_group_entirely(self):
        items = [
            make_item("A001", 30, 8), make_item("A002", 30, 8),
            make_item("A003", 30, 9), make_item("A004", 30, 9),
            make_item("A005", 30, 10), make_item("A006", 30, 10),
            make_item("A007", 30, 10), make_item("A008", 30, 10),
            make_item("A009", 30, 11),
        ]
        result = calculate_fifo_groups(items, Decimal("240"))
        labels = {a.label for a in result.allocations}
        assert "A009" not in labels
        assert len(labels) == 8
        assert result.pool_quantity == Decimal("240")

    def test_200_request_includes_entire_boundary_group(self):
        """200 adet talep — 10.07 grubunun tamamı dahil (240 havuz)."""
        items = [
            make_item("A001", 30, 8), make_item("A002", 30, 8),
            make_item("A003", 30, 9), make_item("A004", 30, 9),
            make_item("A005", 30, 10), make_item("A006", 30, 10),
            make_item("A007", 30, 10), make_item("A008", 30, 10),
            make_item("A009", 30, 11), make_item("A010", 30, 11),
        ]
        result = calculate_fifo_groups(items, Decimal("200"))
        labels = {a.label for a in result.allocations}
        assert {"A005", "A006", "A007", "A008"}.issubset(labels)
        assert "A009" not in labels
        assert "A010" not in labels
        assert result.pool_quantity == Decimal("200")
        assert result.remaining_unfulfilled == Decimal("0")

    def test_no_strict_label_order_required(self):
        """Havuzdaki etiketlerin tamamı eşit allocated_quantity ile gelir."""
        items = [make_item(f"L{i}", 30, i) for i in range(1, 5)]
        result = calculate_fifo_groups(items, Decimal("90"))
        assert len(result.allocations) == 3
        assert result.pool_quantity == Decimal("90")

    def test_insufficient_stock_includes_all_groups(self):
        items = [make_item("A", 30, 8), make_item("B", 30, 9)]
        result = calculate_fifo_groups(items, Decimal("100"))
        assert len(result.allocations) == 2
        assert result.pool_quantity == Decimal("60")
        assert result.remaining_unfulfilled == Decimal("40")

    def test_empty_items(self):
        result = calculate_fifo_groups([], Decimal("100"))
        assert len(result.allocations) == 0
        assert result.remaining_unfulfilled == Decimal("100")

    def test_fifo_calendar_day(self):
        dt = datetime(2026, 7, 10, 17, 41)
        assert fifo_calendar_day(dt).isoformat() == "2026-07-10"

    def test_group_date_ordering_not_label_order(self):
        items = [make_item("B", 30, 5), make_item("A", 30, 1), make_item("C", 30, 3)]
        result = calculate_fifo_groups(items, Decimal("90"))
        dates = [a.fifo_group_date for a in result.allocations]
        assert dates == sorted(dates)
