"""End-to-end operation flow tests."""
import sys
import os
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import Base, get_db
from app.main import app
from app.services.lookup_cache import lookup_cache


def stock_excel() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["ETİKET", "REFERANS", "MİKTAR", "X98FIFO_TARIH"])
    rows = [
        ["A001", "REF-X", 30, "09.07.2026 18:00"],
        ["A002", "REF-X", 30, "10.07.2026 08:15"],
        ["A003", "REF-X", 30, "10.07.2026 09:30"],
        ["A004", "REF-X", 30, "10.07.2026 14:20"],
        ["A005", "REF-X", 30, "11.07.2026 08:00"],
        ["B001", "OTHER", 50, "01.08.2026 10:00"],
    ]
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    lookup_cache._pools.clear()
    lookup_cache._label_data.clear()
    lookup_cache._ref_context.clear()
    lookup_cache._all_labels.clear()
    lookup_cache._global_label_shipment.clear()

    import app.database as db_module
    db_module.SessionLocal = TestSession

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestOperationFlow:
    def test_full_operation_flow(self, client):
        r = client.post("/api/inventory/import/stock", files={
            "file": ("s.xlsx", stock_excel(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        })
        assert r.status_code == 200

        r = client.post("/api/shipment/targets", json={"reference": "REF-X", "target_quantity": 90})
        assert r.status_code == 200

        r = client.post("/api/shipment/find")
        assert r.status_code == 200
        assert len(r.json()["shipments"]) == 1

        r = client.post("/api/shipment/scan", json={"label": "A002"})
        assert r.json()["result"] == "SEVKİYAT ÜRÜNÜ"

        r = client.post("/api/shipment/scan", json={"label": "A002"})
        assert r.json()["result"] == "ZATEN OKUTULDU"

        r = client.post("/api/shipment/scan", json={"label": "A005"})
        assert r.json()["result"] == "SEVKİYAT DIŞI"

        r = client.post("/api/shipment/scan", json={"label": "ZZZZZ"})
        assert r.json()["result"] == "ETİKET BULUNAMADI"

        r = client.post("/api/shipment/scan", json={"label": "B001"})
        assert r.json()["result"] == "SEVKİYAT DIŞI"

    def test_manual_equals_excel_target(self, client):
        client.post("/api/inventory/import/stock", files={
            "file": ("s.xlsx", stock_excel(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        })

        wb = Workbook()
        ws = wb.active
        ws.append(["REFERANS", "MİKTAR"])
        ws.append(["REF-X", 90])
        buf = BytesIO()
        wb.save(buf)

        r = client.post("/api/shipment/targets/import", files={
            "file": ("t.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        })
        assert r.status_code == 200

        r = client.post("/api/shipment/find")
        # Hedef 90, tam FIFO sırasıyla havuz 90 (09.07 + 10.07'den gerektiği kadar)
        assert r.json()["shipments"][0]["pool_quantity"] == 90
        assert r.json()["shipments"][0]["requested_quantity"] == 90

    def test_reset_and_undo_scan(self, client):
        client.post("/api/inventory/import/stock", files={
            "file": ("s.xlsx", stock_excel(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        })
        client.post("/api/shipment/targets", json={"reference": "REF-X", "target_quantity": 90})
        find = client.post("/api/shipment/find")
        shipment_id = find.json()["shipments"][0]["shipment_id"]

        client.post("/api/shipment/scan", json={"label": "A001"})
        client.post("/api/shipment/scan", json={"label": "A002"})

        scanned = client.get(f"/api/shipment/{shipment_id}/scanned")
        assert scanned.status_code == 200
        assert len(scanned.json()) == 2

        undo = client.delete(f"/api/shipment/{shipment_id}/scans/A001")
        assert undo.status_code == 200
        assert undo.json()["scanned_quantity"] == 30

        scanned2 = client.get(f"/api/shipment/{shipment_id}/scanned")
        assert len(scanned2.json()) == 1

        rescan = client.post("/api/shipment/scan", json={"label": "A001"})
        assert rescan.json()["result"] == "SEVKİYAT ÜRÜNÜ"

        reset = client.post("/api/shipment/reset")
        assert reset.status_code == 200
        assert reset.json()["cancelled"] == 1

        status = client.get("/api/shipment/status")
        assert status.json() == []
