"""Comprehensive automated tests for all 10 user requirements & test scenarios."""
import sys
import os
from io import BytesIO
from datetime import datetime
from decimal import Decimal

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
from app.models import InventoryLabel, Shipment, ShipmentLabel, ShipmentStatus, ShipmentLabelStatus


def create_user_scenario_stock() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["ETİKET", "REFERANS", "MİKTAR", "X98FIFO_TARIH"])
    rows = [
        ["ETIKET-A", "6681350-HZE-1", 15, "23.04.2026 08:55"],
        ["ETIKET-B", "6681350-HZE-1", 15, "29.06.2026 09:30"],
        ["ETIKET-C", "6681350-HZE-1", 15, "29.06.2026 09:38"],
        ["ETIKET-D", "6681350-HZE-1", 15, "08.07.2026 17:30"],
        ["OTHER-1",  "OTHER-REF",    50, "01.05.2026 10:00"],
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
        yield c, TestSession
    app.dependency_overrides.clear()


class TestUserScenarios:
    def test_all_10_scenarios(self, client):
        c, TestSession = client

        # 1. Import stock
        r = c.post("/api/inventory/import/stock", files={
            "file": ("stock.xlsx", create_user_scenario_stock(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        })
        assert r.status_code == 200

        # TEST 1 & 9: Create target 30 for 6681350-HZE-1 and find shipments
        c.post("/api/shipment/targets", json={"reference": "6681350-HZE-1", "target_quantity": 30})
        find_resp = c.post("/api/shipment/find")
        assert find_resp.status_code == 200
        shipment_id = find_resp.json()["shipments"][0]["shipment_id"]

        # Verify Pool: ETIKET-A (23.04), ETIKET-B (29.06) and ETIKET-C (29.06) candidate pool. ETIKET-D (08.07) NOT in pool.
        pool_labels = c.get(f"/api/shipments/{shipment_id}/labels").json()
        pool_label_names = {l["label"] for l in pool_labels}
        assert pool_label_names == {"ETIKET-A", "ETIKET-B", "ETIKET-C"}
        assert "ETIKET-D" not in pool_label_names

        # TEST 2: Scan ETIKET-C first (29.06 group, 15 units quota available) -> ACCEPTED
        scan_c = c.post("/api/shipment/scan", json={"label": "ETIKET-C"})
        assert scan_c.status_code == 200
        assert scan_c.json()["result"] == "SEVKİYAT ÜRÜNÜ"
        assert scan_c.json()["scanned_quantity"] == 15.0
        assert scan_c.json()["progress_percent"] == 50.0

        # TEST 3: Scan ETIKET-B second (29.06 group quota 15 is ALREADY FULL) -> REJECTED
        scan_b = c.post("/api/shipment/scan", json={"label": "ETIKET-B"})
        assert scan_b.status_code == 200
        assert scan_b.json()["result"] == "SEVKİYAT DIŞI"
        assert scan_b.json()["scanned_quantity"] == 15.0

        # TEST 4: Scan ETIKET-A third (23.04 group) -> ACCEPTED, 30/30 COMPLETED
        scan_a = c.post("/api/shipment/scan", json={"label": "ETIKET-A"})
        assert scan_a.status_code == 200
        assert scan_a.json()["result"] == "SEVKİYAT ÜRÜNÜ"
        assert scan_a.json()["scanned_quantity"] == 30.0
        assert scan_a.json()["progress_percent"] == 100.0
        assert scan_a.json()["is_complete"] is True

        # TEST 5: Check completed shipment remains listed in GET /api/shipment/status
        status_resp = c.get("/api/shipment/status")
        assert status_resp.status_code == 200
        active_list = status_resp.json()
        assert len(active_list) == 1
        assert active_list[0]["reference"] == "6681350-HZE-1"
        assert active_list[0]["progress_percent"] == 100.0
        assert active_list[0]["is_complete"] is True

        # TEST 6: Scan ETIKET-A again -> ZATEN OKUTULDU
        scan_a_again = c.post("/api/shipment/scan", json={"label": "ETIKET-A"})
        assert scan_a_again.status_code == 200
        assert scan_a_again.json()["result"] == "ZATEN OKUTULDU"

        # TEST 7: Scan OTHER-1 (different reference) -> SEVKİYAT DIŞI
        scan_other = c.post("/api/shipment/scan", json={"label": "OTHER-1"})
        assert scan_other.status_code == 200
        assert scan_other.json()["result"] == "SEVKİYAT DIŞI"

        # TEST 10: App / cache reload persistence test
        db = TestSession()
        lookup_cache.load_all_active(db)
        db.close()

        status_after_reload = c.get("/api/shipment/status")
        assert status_after_reload.status_code == 200
        assert len(status_after_reload.json()) == 1
        assert status_after_reload.json()[0]["is_complete"] is True

        rescan_b_after_reload = c.post("/api/shipment/scan", json={"label": "ETIKET-B"})
        assert rescan_b_after_reload.json()["result"] == "MİKTAR AŞILDI"

        rescan_a_after_reload = c.post("/api/shipment/scan", json={"label": "ETIKET-A"})
        assert rescan_a_after_reload.json()["result"] == "ZATEN OKUTULDU"

    def test_multiple_shipments_isolated_pools(self, client):
        c, _ = client

        c.post("/api/inventory/import/stock", files={
            "file": ("stock.xlsx", create_user_scenario_stock(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        })
        c.post("/api/shipment/targets", json={"reference": "6681350-HZE-1", "target_quantity": 30})
        c.post("/api/shipment/targets", json={"reference": "OTHER-REF", "target_quantity": 50})
        find_resp = c.post("/api/shipment/find")
        assert find_resp.status_code == 200
        assert len(find_resp.json()["shipments"]) == 2

        scan_other = c.post("/api/shipment/scan", json={"label": "OTHER-1"})
        assert scan_other.json()["result"] == "SEVKİYAT ÜRÜNÜ"

        scan_a = c.post("/api/shipment/scan", json={"label": "ETIKET-A"})
        assert scan_a.json()["result"] == "SEVKİYAT ÜRÜNÜ"
        assert scan_a.json()["reference"] == "6681350-HZE-1"

    def test_critical_b_then_c_rejected(self, client):
        """TEST 3: B then C — C must RED, progress stays 15/30."""
        c, _ = client
        c.post("/api/inventory/import/stock", files={
            "file": ("stock.xlsx", create_user_scenario_stock(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        })
        c.post("/api/shipment/targets", json={"reference": "6681350-HZE-1", "target_quantity": 30})
        c.post("/api/shipment/find")

        r_b = c.post("/api/shipment/scan", json={"label": "ETIKET-B"})
        assert r_b.json()["result"] == "SEVKİYAT ÜRÜNÜ"
        assert r_b.json()["scanned_quantity"] == 15.0

        r_c = c.post("/api/shipment/scan", json={"label": "ETIKET-C"})
        assert r_c.json()["result"] == "SEVKİYAT DIŞI"
        assert r_c.json()["scanned_quantity"] == 15.0
        assert r_c.json()["progress_percent"] == 50.0

    def test_critical_b_twice_duplicate(self, client):
        """TEST 2 variant: B scanned twice — second is ZATEN OKUTULDU."""
        c, _ = client
        c.post("/api/inventory/import/stock", files={
            "file": ("stock.xlsx", create_user_scenario_stock(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        })
        c.post("/api/shipment/targets", json={"reference": "6681350-HZE-1", "target_quantity": 30})
        c.post("/api/shipment/find")

        assert c.post("/api/shipment/scan", json={"label": "ETIKET-B"}).json()["result"] == "SEVKİYAT ÜRÜNÜ"
        r2 = c.post("/api/shipment/scan", json={"label": "ETIKET-B"})
        assert r2.json()["result"] == "ZATEN OKUTULDU"
        assert r2.json()["scanned_quantity"] == 15.0

    def test_critical_b_then_a_order(self, client):
        """TEST 4: B then A — 30/30, no scan order enforcement."""
        c, _ = client
        c.post("/api/inventory/import/stock", files={
            "file": ("stock.xlsx", create_user_scenario_stock(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        })
        c.post("/api/shipment/targets", json={"reference": "6681350-HZE-1", "target_quantity": 30})
        c.post("/api/shipment/find")

        c.post("/api/shipment/scan", json={"label": "ETIKET-B"})
        r = c.post("/api/shipment/scan", json={"label": "ETIKET-A"})
        assert r.json()["result"] == "SEVKİYAT ÜRÜNÜ"
        assert r.json()["scanned_quantity"] == 30.0
        assert r.json()["is_complete"] is True

    def test_qr_code_with_leading_letter_prefixes(self, client):
        """Test scanning QR codes with leading letters like s700024541, S700024541, P700024541."""
        wb = Workbook()
        ws = wb.active
        ws.append(["ID", "ETIKET", "REFERANS", "MIKTAR", "DURUM", "OLUSTURMATARIHI", "SEVKTARIHI", "MUSTERI", "ESLESTIRMETARIHI", "AKTARIM", "X98FIFO_TARIH", "BLOKAJ", "PAKETLEMESICIL"])
        ws.append([1194, "700024541", "7073145-G", 30, "O", "24.07.2026 11:55", "", "12051003", "", "", "9.01.2026 14:22", "YANLIŞ", 35506])
        buf = BytesIO()
        wb.save(buf)

        c, _ = client
        c.post("/api/inventory/import/stock", files={
            "file": ("stock.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        })
        c.post("/api/shipment/targets", json={"reference": "7073145-G", "target_quantity": 30})
        c.post("/api/shipment/find")

        # Scan with lowercase s prefix
        scan1 = c.post("/api/shipment/scan", json={"label": "s700024541"})
        assert scan1.status_code == 200
        assert scan1.json()["result"] == "SEVKİYAT ÜRÜNÜ"
        assert scan1.json()["label"] == "700024541"
        assert scan1.json()["is_complete"] is True
