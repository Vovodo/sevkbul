"""End-to-end API test — operation flow."""
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


def create_stock_excel() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["ETİKET", "REFERANS", "MİKTAR", "X98FIFO_TARIH"])
    rows = [
        ["A001", "6681378-HZN-1", 30, "08.07.2026 10:00"],
        ["A002", "6681378-HZN-1", 30, "08.07.2026 14:00"],
        ["A003", "6681378-HZN-1", 30, "09.07.2026 10:00"],
        ["A004", "6681378-HZN-1", 30, "09.07.2026 11:00"],
        ["A005", "6681378-HZN-1", 30, "10.07.2026 08:00"],
        ["A006", "6681378-HZN-1", 30, "10.07.2026 09:00"],
        ["A007", "6681378-HZN-1", 30, "10.07.2026 14:00"],
        ["A008", "6681378-HZN-1", 30, "10.07.2026 17:00"],
        ["A009", "6681378-HZN-1", 30, "11.07.2026 10:00"],
        ["800001", "OTHER-REF", 50, "01.08.2026 10:00"],
    ]
    for row in rows:
        ws.append(row)
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


class TestE2E:
    def test_dual_excel_fifo_group_flow(self, client):
        r = client.post("/api/inventory/import/stock", files={
            "file": ("stock.xlsx", create_stock_excel(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        })
        assert r.status_code == 200

        r = client.post("/api/shipment/targets", json={"reference": "6681378-HZN-1", "target_quantity": 240})
        assert r.status_code == 200

        r = client.post("/api/shipment/find")
        assert r.status_code == 200
        data = r.json()
        assert len(data["shipments"]) == 1
        assert data["shipments"][0]["pool_quantity"] == 240

        r = client.post("/api/shipment/scan", json={"label": "A006"})
        assert r.json()["result"] == "SEVKİYAT ÜRÜNÜ"

        r = client.post("/api/shipment/scan", json={"label": "A006"})
        assert r.json()["result"] == "ZATEN OKUTULDU"

        r = client.post("/api/shipment/scan", json={"label": "A009"})
        assert r.json()["result"] == "SEVKİYAT DIŞI"

        r = client.post("/api/shipment/scan", json={"label": "800001"})
        assert r.json()["result"] == "SEVKİYAT DIŞI"

        r = client.post("/api/shipment/scan", json={"label": "999999"})
        assert r.json()["result"] == "ETİKET BULUNAMADI"

    def test_shipment_excel_targets_import(self, client):
        client.post("/api/inventory/import/stock", files={
            "file": ("stock.xlsx", create_stock_excel(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        })

        wb = Workbook()
        ws = wb.active
        ws.append(["REFERANS", "MİKTAR"])
        ws.append(["6681378-HZN-1", 90])
        ws.append(["OTHER-REF", 50])
        buf = BytesIO()
        wb.save(buf)

        r = client.post("/api/shipment/targets/import", files={
            "file": ("ship.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        })
        assert r.status_code == 200
        assert r.json()["successful"] == 2
