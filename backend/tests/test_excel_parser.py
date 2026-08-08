import pytest
from datetime import datetime
from decimal import Decimal

from app.utils.excel_parser import (
    normalize_header, find_column_mapping,
    parse_quantity, parse_fifo_datetime, parse_fifo_date,
    parse_label, parse_reference, format_fifo_datetime,
)
from app.services.fifo_engine import calculate_fifo_groups, InventoryItem, fifo_calendar_day


class TestExcelParser:
    def test_normalize_header_turkish(self):
        assert normalize_header("  ETİKET  ") == "ETIKET"
        assert normalize_header("X98FIFO_TARIH") == "X98FIFO_TARIH"
        assert normalize_header("MİKTAR") == "MIKTAR"
        assert normalize_header("Referans") == "REFERANS"

    def test_find_column_mapping_by_header_not_letter(self):
        """Kolon harfine değil başlığa göre eşleşme — B,C,D,K pozisyonları örnek."""
        headers = ["SIRA", "ETİKET", "REFERANS", "MİKTAR", "E", "F", "G", "H", "I", "J", "X98FIFO_TARIH"]
        mapping = find_column_mapping(headers)
        assert mapping["label"] == 1
        assert mapping["reference"] == 2
        assert mapping["quantity"] == 3
        assert mapping["fifo_date"] == 10

    def test_find_column_mapping_with_paketlemesicil(self):
        """PAKETLEMESICIL başlığı varken ETIKET'in ETIKET kolonuna (Col B) doğru haritalanması."""
        headers = ["ID", "ETIKET", "REFERANS", "MIKTAR", "DURUM", "OLUSTURMATARIHI", "SEVKTARIHI", "MUSTERI", "ESLESTIRMETARIHI", "AKTARIM", "X98FIFO_TARIH", "BLOKAJ", "PAKETLEMESICIL"]
        mapping = find_column_mapping(headers)
        assert mapping["label"] == 1
        assert mapping["reference"] == 2
        assert mapping["quantity"] == 3
        assert mapping["fifo_date"] == 10

    def test_parse_quantity(self):
        assert parse_quantity(30) == Decimal("30")
        assert parse_quantity("30") == Decimal("30")
        assert parse_quantity("30,5") == Decimal("30.5")
        assert parse_quantity("") is None
        assert parse_quantity("abc") is None
        assert parse_quantity(0) is None

    def test_parse_fifo_datetime_string_with_time(self):
        dt = parse_fifo_datetime("23.07.2026 22:22")
        assert dt == datetime(2026, 7, 23, 22, 22, 0)
        assert dt.hour == 22
        assert dt.minute == 22

    def test_parse_fifo_datetime_single_digit_day_month(self):
        dt1 = parse_fifo_datetime("4.08.2026 17:16")
        dt2 = parse_fifo_datetime("04.08.2026 17:16")
        assert dt1 == dt2
        assert dt1 == datetime(2026, 8, 4, 17, 16, 0)

    def test_parse_fifo_datetime_single_digit_hour(self):
        dt = parse_fifo_datetime("5.08.2026 8:37")
        assert dt == datetime(2026, 8, 5, 8, 37, 0)

    def test_parse_fifo_datetime_real_world_samples(self):
        samples = [
            ("23.07.2026 22:22", datetime(2026, 7, 23, 22, 22)),
            ("25.07.2026 09:13", datetime(2026, 7, 25, 9, 13)),
            ("13.03.2026 08:20", datetime(2026, 3, 13, 8, 20)),
            ("27.02.2026 12:06", datetime(2026, 2, 27, 12, 6)),
        ]
        for text, expected in samples:
            dt = parse_fifo_datetime(text)
            assert dt == expected, f"Failed for {text}"

    def test_parse_fifo_datetime_python_datetime_preserved(self):
        original = datetime(2026, 7, 10, 14, 20, 30)
        result = parse_fifo_datetime(original)
        assert result.hour == 14
        assert result.minute == 20
        assert result.second == 30

    def test_parse_fifo_datetime_excel_serial(self):
        # 10.07.2026 ~ serial 45848 + time fraction
        serial = 45848 + (8 * 60 + 15) / 1440  # 08:15 on that day
        dt = parse_fifo_datetime(serial)
        assert dt is not None
        assert dt.hour == 8
        assert dt.minute == 15

    def test_parse_fifo_datetime_does_not_strip_time(self):
        dt = parse_fifo_datetime("04.08.2026 17:16")
        assert not (dt.hour == 0 and dt.minute == 0)

    def test_format_fifo_datetime(self):
        dt = datetime(2026, 7, 23, 22, 22)
        assert format_fifo_datetime(dt) == "23.07.2026 22:22"

    def test_parse_fifo_date_alias(self):
        dt = parse_fifo_date("23.07.2026 22:22")
        assert dt.hour == 22

    def test_parse_label_as_string(self):
        assert parse_label(700024778) == "700024778"
        assert parse_label(700024778.0) == "700024778"
        assert parse_label("  700024778  ") == "700024778"

    def test_parse_reference_not_numeric(self):
        assert parse_reference("6681378-HZN-1") == "6681378-HZN-1"
        assert parse_reference(" 6681378-HZN-1 ") == "6681378-HZN-1"
        assert parse_reference("") is None

    def test_invalid_fifo_returns_none(self):
        assert parse_fifo_datetime("not-a-date") is None
        assert parse_fifo_datetime("") is None
        assert parse_fifo_datetime(None) is None


class TestFifoDatetimeSorting:
    def test_full_datetime_sort_order(self):
        """A004 (09.07 18:00) → A001,A002,A003 (10.07) → A005 (11.07)"""
        items = [
            InventoryItem("A001", "X", Decimal("30"), datetime(2026, 7, 10, 8, 15)),
            InventoryItem("A002", "X", Decimal("30"), datetime(2026, 7, 10, 9, 30)),
            InventoryItem("A003", "X", Decimal("30"), datetime(2026, 7, 10, 14, 20)),
            InventoryItem("A004", "X", Decimal("30"), datetime(2026, 7, 9, 18, 0)),
            InventoryItem("A005", "X", Decimal("30"), datetime(2026, 7, 11, 8, 0)),
        ]
        sorted_items = sorted(items, key=lambda x: x.fifo_date)
        assert [i.label for i in sorted_items] == ["A004", "A001", "A002", "A003", "A005"]

    def test_same_day_different_times_same_group(self):
        items = [
            InventoryItem("A001", "X", Decimal("30"), datetime(2026, 7, 10, 8, 15)),
            InventoryItem("A002", "X", Decimal("30"), datetime(2026, 7, 10, 18, 45)),
        ]
        assert fifo_calendar_day(items[0].fifo_date) == fifo_calendar_day(items[1].fifo_date)
        assert items[0].fifo_date < items[1].fifo_date

    def test_same_day_group_in_fifo_pool(self):
        items = [
            InventoryItem("A001", "X", Decimal("30"), datetime(2026, 7, 10, 8, 15)),
            InventoryItem("A002", "X", Decimal("30"), datetime(2026, 7, 10, 9, 30)),
            InventoryItem("A003", "X", Decimal("30"), datetime(2026, 7, 10, 14, 20)),
            InventoryItem("A004", "X", Decimal("30"), datetime(2026, 7, 9, 18, 0)),
        ]
        result = calculate_fifo_groups(items, Decimal("90"))
        labels = [a.label for a in result.allocations]
        assert "A004" in labels
        assert "A001" in labels
        assert "A002" in labels
        assert "A003" in labels
        assert labels.index("A004") < labels.index("A001")
