import pytest
from decimal import Decimal
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import InventoryLabel, Shipment, ShipmentLabel, ScanLog, ShipmentTarget
from app.services.excel_import import import_excel
from app.services.target_service import add_target, find_shipments
from app.services.scan_service import process_scan
from app.services.lookup_cache import lookup_cache


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    lookup_cache._pools.clear()
    lookup_cache._label_data.clear()
    lookup_cache._ref_context.clear()
    lookup_cache._all_labels.clear()
    yield session
    session.close()


def create_stock_excel() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["ETİKET", "REFERANS", "MİKTAR", "X98FIFO_TARIH"])
    for label, day in [("A001", 8), ("A002", 8), ("A003", 9), ("A004", 10), ("B001", 1)]:
        ref = "REF-1" if label.startswith("A") else "REF-2"
        ws.append([label, ref, 30, f"{day:02d}.07.2026 10:00"])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def create_shipment_excel(ref: str, qty: int) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["REFERANS", "MİKTAR"])
    ws.append([ref, qty])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestIntegration:
    def test_full_flow_with_fifo_groups(self, db):
        import_excel(db, create_stock_excel())
        lookup_cache.reload_inventory_labels(db)

        add_target(db, "REF-1", Decimal("90"))
        find_result = find_shipments(db)
        sid = find_result["shipments"][0]["shipment_id"]

        r1 = process_scan(db, sid, "A001")
        assert r1.result == "SEVKİYAT ÜRÜNÜ"

        r2 = process_scan(db, sid, "A001")
        assert r2.result == "ZATEN OKUTULDU"

        r3 = process_scan(db, sid, "B001")
        assert r3.result == "SEVKİYAT DIŞI"

        r4 = process_scan(db, sid, "999999")
        assert r4.result == "ETİKET BULUNAMADI"

        r_outside = process_scan(db, sid, "A004")
        assert r_outside.result == "SEVKİYAT DIŞI"

        process_scan(db, sid, "A002")
        r5 = process_scan(db, sid, "A003")
        assert r5.is_complete is True
