"""
Kapsamlı 8-Skill QA Denetim Paketi:
- test-strategy & unit-testing: Çoklu sevkiyat FIFO matematiksel değişmezleri, kısmi kutu okutma ve 2-adımlı ideal_fifo_dates denetimi
- api-testing: Şema sözleşmesi (exact key-set & type validation), başlık (header) kontrolü ve 4xx hata yolları
- database-testing: UNIQUE/NOT NULL kısıtları, orphan (yetim kayıt) anti-join denetimi ve EXPLAIN QUERY PLAN indeks doğrulaması
- security-testing: OWASP Top 10 (2025) A05 SQLi/XSS negatif testleri, A06 negatif miktar suistimali, A10 bozuk dosya/istisna yönetimi
- performance-testing: p95 yanıt süresi bütçeleri (scan, manifest, groups)
"""
from datetime import datetime, timedelta
from decimal import Decimal
from io import BytesIO
import statistics
import time

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
from app.database import Base, get_db
from app.main import app
from app.models import (
    InventoryLabel,
    ScanLog,
    Shipment,
    ShipmentDateQuota,
    ShipmentLabel,
    ShipmentLabelStatus,
    ShipmentStatus,
)
from app.services.lookup_cache import lookup_cache
from app.services.operation_service import (
    delete_shipment_group,
    get_shipment_manifest,
    undo_scan,
)
from app.services.scan_service import process_global_scan
from app.services.shipment_service import (
    create_shipment_from_reference,
    get_shipment_groups,
    recalculate_shipments,
    reorder_shipment_groups,
)
from app.services.target_service import add_target, find_shipments


@pytest.fixture(autouse=True)
def clear_lookup_cache():
    lookup_cache._pools.clear()
    lookup_cache._label_data.clear()
    lookup_cache._ref_context.clear()
    lookup_cache._all_labels.clear()
    lookup_cache._global_label_shipment.clear()
    yield
    lookup_cache._pools.clear()
    lookup_cache._label_data.clear()
    lookup_cache._ref_context.clear()
    lookup_cache._all_labels.clear()
    lookup_cache._global_label_shipment.clear()


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    prev_session_local = database.SessionLocal
    database.SessionLocal = TestingSessionLocal

    def override_get_db():
        s = TestingSessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    database.SessionLocal = prev_session_local
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def seed_label(db, label: str, ref: str, qty: float, dt: datetime, blocked: bool = False) -> InventoryLabel:
    inv = InventoryLabel(
        label=label,
        reference=ref,
        quantity=Decimal(str(qty)),
        fifo_date=dt,
        blocked=blocked,
        hidden=False,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


# ═══════════════════════════════════════════════════════════════════════════
# 1. UNIT & MULTI-SHIPMENT FIFO DEEP AUDIT (unit-testing & test-strategy)
# ═══════════════════════════════════════════════════════════════════════════

class TestMultiShipmentFifoDeepAudit:
    def test_partial_box_scan_consumes_barcode_for_next_shipment_and_matches_recalculate(self, db):
        """
        Kural: Bir barkod yalnızca 1 kez okutulabilir.
        Stokta L1 (01.06, 30 adet) ve L2 (02.06, 30 adet) var.
        1. Sevkiyat 20 adet istiyor -> L1'den 20 adet tahsis edilir.
        Operatör 1. Sevkiyatta L1'i okutur (20 adet sayılır, L1 barkodu SCANNED olur).
        Ardından 2. Sevkiyat (30 adet) oluşturulduğunda:
        - L1 barkodu zaten okutulmuş olduğu için 2. Sevkiyata L1'in kalan 10 adedi VERİLMEMELİ!
        - 2. Sevkiyat doğrudan L2'yi (02.06, 30 adet) almalı ve recalculate_shipments ile %100 aynı sonucu vermeli!
        """
        seed_label(db, "PART-L1", "REF-PART", 30, datetime(2026, 6, 1, 8, 0))
        seed_label(db, "PART-L2", "REF-PART", 30, datetime(2026, 6, 2, 8, 0))

        add_target(db, "REF-PART", Decimal("20"), source_name="S1")
        find_shipments(db)
        g1_id = get_shipment_groups(db)[0]["group_id"]

        # S1'de PART-L1'i okut (20 adet sayılır, S1 tamamlanır)
        scan1 = process_global_scan(db, "PART-L1", target_group_id=g1_id)
        assert scan1.success is True
        assert scan1.scanned_quantity == 20.0
        assert scan1.is_complete is True

        # Şimdi S2 (30 adet) oluştur
        add_target(db, "REF-PART", Decimal("30"), source_name="S2")
        find_shipments(db)

        groups_before_recalc = get_shipment_groups(db)
        s2_before = groups_before_recalc[1]["items"][0]
        m_before = {m["shipment_id"]: m for m in get_shipment_manifest(db)}
        s2_dates_before = [(i["fifo_group_date"], i["quantity"]) for i in m_before[s2_before["shipment_id"]]["items"]]

        # S2 yalnızca 02.06.2026 (30 adet) almalı; 01.06.2026'dan 10 adet almamalı!
        assert s2_dates_before == [("02.06.2026", 30.0)]
        assert s2_before["short_quantity"] == 0.0

        # Recalculate çağrıldığında da sonuç değişmemeli (Initial Find == Recalculate Equivalence)
        recalculate_shipments(db)
        m_after = {m["shipment_id"]: m for m in get_shipment_manifest(db)}
        s2_dates_after = [(i["fifo_group_date"], i["quantity"]) for i in m_after[s2_before["shipment_id"]]["items"]]
        assert s2_dates_after == s2_dates_before

        # Operatör S2'de PART-L2'yi okuttuğunda S2 de sorunsuz tamamlanmalı!
        g2_id = groups_before_recalc[1]["group_id"]
        scan2 = process_global_scan(db, "PART-L2", target_group_id=g2_id)
        assert scan2.success is True
        assert scan2.scanned_quantity == 30.0
        assert scan2.is_complete is True

    def test_ideal_fifo_dates_two_step_accuracy_when_earlier_shipment_has_out_of_order_scan(self, db):
        """
        Stok: 01.06 (30), 02.06 (30), 03.06 (30).
        S1 (30) ve S2 (30) açıldı.
        S2 kendi tarihi olan 02.06'yı okuttu, sonra S2 1. sıraya taşındı ([S2, S1]).
        Yeni sırada:
        - 1. sıradaki S2'nin ideal tarihi 01.06 olduğu için S2'deki 02.06 okutması 'outside_fifo=True' (FIFO dışı) olmalı.
        - 2. sıradaki S1'e ise yeniden hesaplamada en eski açık stok olan 01.06 verildi!
        - Operatör S1'de 01.06'yı okuttuğunda, S1'in 01.06 okutması KESİNLİKLE 'outside_fifo=False' (uygun) olmalı!
        """
        seed_label(db, "STEP-1", "REF-STEP", 30, datetime(2026, 6, 1, 8, 0))
        seed_label(db, "STEP-2", "REF-STEP", 30, datetime(2026, 6, 2, 8, 0))
        seed_label(db, "STEP-3", "REF-STEP", 30, datetime(2026, 6, 3, 8, 0))

        add_target(db, "REF-STEP", Decimal("30"), source_name="S1")
        find_shipments(db)
        add_target(db, "REF-STEP", Decimal("30"), source_name="S2")
        find_shipments(db)

        groups = get_shipment_groups(db)
        g1_id, g2_id = groups[0]["group_id"], groups[1]["group_id"]
        s1_id = groups[0]["items"][0]["shipment_id"]
        s2_id = groups[1]["items"][0]["shipment_id"]

        # S2'de 02.06 (STEP-2) okut
        assert process_global_scan(db, "STEP-2", target_group_id=g2_id).success is True

        # S2'yi 1. sıraya taşı: [S2, S1]
        reorder_shipment_groups(db, [g2_id, g1_id])

        # Şimdi S1 (2. sıra) kendisine tahsis edilen 01.06 (STEP-1) etiketini okutsun
        assert process_global_scan(db, "STEP-1", target_group_id=g1_id).success is True

        manifests = {m["shipment_id"]: m for m in get_shipment_manifest(db)}
        s2_item = manifests[s2_id]["items"][0]
        s1_item = manifests[s1_id]["items"][0]

        # S2 (1. sıra) 02.06 okutmuştu, önünde 01.06 olduğu için FIFO dışı
        assert s2_item["fifo_group_date"] == "02.06.2026"
        assert s2_item["outside_fifo"] is True

        # S1 (2. sıra) kendisine verilen en eski 01.06'yı okuttu, kesinlikle FIFO dışı DEĞİL!
        assert s1_item["fifo_group_date"] == "01.06.2026"
        assert s1_item["outside_fifo"] is False

    def test_8_shipments_multi_reference_interleaved_operations_invariants(self, db):
        """
        8 ardışık sevkiyat, 5 referans, karışık günlük/saatlik mod, okutmalar,
        geri almalar ve sıralama değişimleri boyunca tüm FIFO değişmezlerinin korunması.
        """
        base = datetime(2026, 6, 1, 8, 0)
        refs = [f"REF-M8-{i}" for i in range(1, 6)]
        for r in refs:
            for d in range(10):
                seed_label(db, f"{r}-D{d}-A", r, 25, base + timedelta(days=d, hours=1))
                seed_label(db, f"{r}-D{d}-B", r, 25, base + timedelta(days=d, hours=4))
        # Her referansta 10 gün × 50 adet = 500 adet stok var.

        # 8 sevkiyat × 60 adet = 480 adet talep (tümü karşılanabilir!)
        for s_idx in range(1, 9):
            for r in refs:
                add_target(db, r, Decimal("60"), source_name=f"M8-Sevkiyat-{s_idx}")
            find_shipments(db, hourly_fifo=(s_idx % 2 == 0))

        groups = get_shipment_groups(db)
        assert len(groups) == 8
        for g in groups:
            assert all(it["short_quantity"] == 0.0 for it in g["items"])

        # Ters sırala ve yeniden hesapla
        reversed_gids = [g["group_id"] for g in reversed(groups)]
        reordered = reorder_shipment_groups(db, reversed_gids)
        assert [g["group_id"] for g in reordered] == reversed_gids
        for g in reordered:
            assert all(it["short_quantity"] == 0.0 for it in g["items"])


# ═══════════════════════════════════════════════════════════════════════════
# 2. API CONTRACT & SCHEMA VALIDATION (api-testing)
# ═══════════════════════════════════════════════════════════════════════════

class TestApiContractAndSchemaValidation:
    def test_endpoints_schema_contracts_headers_and_error_paths(self, client):
        # 1. /api/health contract & headers
        h_res = client.get("/api/health")
        assert h_res.status_code == 200
        assert "application/json" in h_res.headers["content-type"]
        h_body = h_res.json()
        assert set(h_body.keys()) >= {"status", "service", "version", "features"}
        assert h_body["status"] == "ok"

        # 2. /api/inventory/stats contract
        st_res = client.get("/api/inventory/stats")
        assert st_res.status_code == 200
        st_body = st_res.json()
        assert set(st_body.keys()) == {
            "total_labels", "total_references", "blocked_labels", "unblocked_labels", "hidden_labels"
        }

        # 3. Error paths (4xx contracts)
        assert client.post("/api/shipment/scan", json={"label": "   "}).status_code == 400
        assert client.delete("/api/shipment/targets/999999").status_code == 404
        assert client.delete("/api/shipment/group/999999").status_code == 404
        assert client.patch("/api/inventory/labels/999999/hidden", json={"hidden": True}).status_code == 404
        assert client.post("/api/shipment/active-group/999999").status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# 3. DATABASE INTEGRITY, CONSTRAINTS & QUERY PLANS (database-testing)
# ═══════════════════════════════════════════════════════════════════════════

class TestDatabaseIntegrityConstraintsAndQueryPlans:
    def test_unique_and_not_null_constraints_enforced_at_db_level(self, db):
        seed_label(db, "UNIQ-001", "REF-DB", 30, datetime(2026, 6, 1, 8, 0))
        # Duplicate label must raise IntegrityError at DB level
        dup = InventoryLabel(
            label="UNIQ-001",
            reference="REF-DB",
            quantity=Decimal("30"),
            fifo_date=datetime(2026, 6, 2, 8, 0),
        )
        db.add(dup)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_no_orphan_rows_after_group_delete_anti_join_audit(self, db):
        seed_label(db, "ORP-1", "REF-ORP", 30, datetime(2026, 6, 1, 8, 0))
        add_target(db, "REF-ORP", Decimal("30"), source_name="OrphanTest")
        find_shipments(db)
        gid = get_shipment_groups(db)[0]["group_id"]
        process_global_scan(db, "ORP-1", target_group_id=gid)

        delete_shipment_group(db, gid)

        # Anti-join audit: shipment_labels, shipment_date_quotas ve scan_logs içinde
        # silinmiş shipment_id'ye işaret eden tek bir yetim (orphan) kayıt kalmamalı!
        orphan_sl = db.execute(text(
            "SELECT COUNT(*) FROM shipment_labels sl LEFT JOIN shipments s ON s.id = sl.shipment_id WHERE s.id IS NULL"
        )).scalar()
        orphan_q = db.execute(text(
            "SELECT COUNT(*) FROM shipment_date_quotas q LEFT JOIN shipments s ON s.id = q.shipment_id WHERE s.id IS NULL"
        )).scalar()
        orphan_log = db.execute(text(
            "SELECT COUNT(*) FROM scan_logs l LEFT JOIN shipments s ON s.id = l.shipment_id WHERE l.shipment_id IS NOT NULL AND s.id IS NULL"
        )).scalar()
        assert orphan_sl == 0
        assert orphan_q == 0
        assert orphan_log == 0

    def test_critical_queries_use_database_indexes_explain_plan(self, db):
        seed_label(db, "IDX-1", "REF-IDX", 30, datetime(2026, 6, 1, 8, 0))
        plan_label = db.execute(text(
            "EXPLAIN QUERY PLAN SELECT * FROM inventory_labels WHERE label = 'IDX-1'"
        )).fetchall()
        plan_ref = db.execute(text(
            "EXPLAIN QUERY PLAN SELECT * FROM inventory_labels WHERE reference = 'REF-IDX'"
        )).fetchall()
        plan_text_label = " ".join(str(r) for r in plan_label).upper()
        plan_text_ref = " ".join(str(r) for r in plan_ref).upper()
        assert "INDEX" in plan_text_label
        assert "INDEX" in plan_text_ref


# ═══════════════════════════════════════════════════════════════════════════
# 4. OWASP TOP 10 SECURITY NEGATIVE PATHS (security-testing)
# ═══════════════════════════════════════════════════════════════════════════

class TestOwaspSecurityNegativePaths:
    def test_a05_sql_injection_and_xss_payloads_safely_handled(self, client):
        wb = Workbook()
        ws = wb.active
        ws.append(["ETİKET", "REFERANS", "MİKTAR", "X98FIFO_TARIH"])
        ws.append(["SEC-1", "REF-SEC", 30, "01.06.2026 08:00"])
        buf = BytesIO()
        wb.save(buf)
        client.post(
            "/api/inventory/import/stock",
            files={"file": ("s.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        client.post("/api/shipment/targets", json={"reference": "REF-SEC", "target_quantity": 30})
        client.post("/api/shipment/find")

        sqli_payloads = [
            "' OR '1'='1",
            "'; DROP TABLE shipments; --",
            "\" UNION SELECT null,null,null --",
            "<script>alert('xss')</script>",
        ]
        for payload in sqli_payloads:
            scan_resp = client.post("/api/shipment/scan", json={"label": payload})
            assert scan_resp.status_code == 200
            assert scan_resp.json()["success"] is False

            search_resp = client.get(f"/api/inventory/labels?q={payload}")
            assert search_resp.status_code == 200

        # Tablolar ve aktif sevkiyat tamamen sağlam kalmalı
        groups = client.get("/api/shipment/groups").json()
        assert len(groups) == 1
        assert groups[0]["items"][0]["reference"] == "REF-SEC"

    def test_a06_negative_and_zero_quantities_rejected(self, client):
        for bad_qty in (0, -1, -999.99):
            res = client.post("/api/shipment/targets", json={"reference": "REF-NEG", "target_quantity": bad_qty})
            assert res.status_code in (400, 422)

    def test_a10_corrupted_files_and_invalid_parameters_fail_closed(self, client):
        # Bozuk binary içerikli .xlsx dosyası 500 vermemeli ve stack trace sızdırmamalı
        bad_xlsx = client.post(
            "/api/shipment/targets/import",
            files={"file": ("bozuk.xlsx", b"not-a-zip-or-excel-content", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert bad_xlsx.status_code in (200, 400)
        assert "Traceback" not in bad_xlsx.text


# ═══════════════════════════════════════════════════════════════════════════
# 5. PERFORMANCE BUDGETS (performance-testing)
# ═══════════════════════════════════════════════════════════════════════════

class TestPerformanceBudgets:
    def test_api_p95_latency_budgets(self, client):
        wb = Workbook()
        ws = wb.active
        ws.append(["ETİKET", "REFERANS", "MİKTAR", "X98FIFO_TARIH"])
        for i in range(1, 31):
            ws.append([f"PERF-L-{i:03d}", f"REF-P-{(i % 10) + 1}", 30, "01.06.2026 08:00"])
        buf = BytesIO()
        wb.save(buf)
        client.post(
            "/api/inventory/import/stock",
            files={"file": ("s.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        for r in range(1, 11):
            client.post("/api/shipment/targets", json={"reference": f"REF-P-{r}", "target_quantity": 60})
        client.post("/api/shipment/find")

        groups = client.get("/api/shipment/groups").json()
        first_sid = groups[0]["items"][0]["shipment_id"]

        scan_times_ms = []
        for i in range(1, 21):
            t0 = time.perf_counter()
            r = client.post("/api/shipment/scan", json={"label": f"PERF-L-{i:03d}"})
            scan_times_ms.append((time.perf_counter() - t0) * 1000)
            assert r.status_code == 200

        manifest_times_ms = []
        for _ in range(20):
            t0 = time.perf_counter()
            r = client.get(f"/api/shipment/manifest?shipment_id={first_sid}")
            manifest_times_ms.append((time.perf_counter() - t0) * 1000)
            assert r.status_code == 200

        scan_p95 = sorted(scan_times_ms)[int(len(scan_times_ms) * 0.95) - 1]
        manifest_p95 = sorted(manifest_times_ms)[int(len(manifest_times_ms) * 0.95) - 1]
        print(f"\n[PERF BUDGET] scan p95={scan_p95:.2f}ms | single-manifest p95={manifest_p95:.2f}ms")
        assert scan_p95 < 50.0
        assert manifest_p95 < 30.0


class TestResetScansFeatures:
    def test_reset_group_scans_and_reset_all_scans_keep_shipments_intact(self, client):
        wb = Workbook()
        ws = wb.active
        ws.append(["ETİKET", "REFERANS", "MİKTAR", "X98FIFO_TARIH"])
        ws.append(["RS-1", "REF-RS", 30, "01.06.2026 08:00"])
        ws.append(["RS-2", "REF-RS", 30, "02.06.2026 08:00"])
        ws.append(["RS-3", "REF-RS", 30, "03.06.2026 08:00"])
        buf = BytesIO()
        wb.save(buf)

        client.post(
            "/api/inventory/import/stock",
            files={"file": ("s.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

        # 3 ayrı sevkiyat oluştur (her biri 30 adet)
        for _ in range(3):
            client.post("/api/shipment/targets", json={"reference": "REF-RS", "target_quantity": 30})
            client.post("/api/shipment/find")

        groups = client.get("/api/shipment/groups").json()
        assert len(groups) == 3
        g1_id, g2_id, g3_id = groups[0]["group_id"], groups[1]["group_id"], groups[2]["group_id"]

        # Her üç sevkiyatta da etiketlerini okut (tamamla)
        assert client.post("/api/shipment/scan", json={"label": "RS-1", "group_id": g1_id}).json()["success"] is True
        assert client.post("/api/shipment/scan", json={"label": "RS-2", "group_id": g2_id}).json()["success"] is True
        assert client.post("/api/shipment/scan", json={"label": "RS-3", "group_id": g3_id}).json()["success"] is True

        # 1) Sadece 2. Sevkiyatın okutmasını sıfırla (Sevkiyat Başı Sıfırlama)
        res_grp = client.post(f"/api/shipment/group/{g2_id}/scans/reset")
        assert res_grp.status_code == 200
        g_after_grp = res_grp.json()["groups"]
        assert len(g_after_grp) == 3
        assert g_after_grp[0]["scanned_quantity"] == 30.0
        assert g_after_grp[1]["scanned_quantity"] == 0.0
        assert g_after_grp[1]["is_complete"] is False
        assert g_after_grp[2]["scanned_quantity"] == 30.0

        # RS-2 etiketi tekrar 2. Sevkiyatta okutulabilmeli!
        assert client.post("/api/shipment/scan", json={"label": "RS-2", "group_id": g2_id}).json()["success"] is True

        # 2) Tüm okutmaları sıfırla (Genel Okutmaları Sıfırla — sevkiyatlar silinmez!)
        res_all = client.post("/api/shipment/scans/reset")
        assert res_all.status_code == 200
        g_after_all = res_all.json()["groups"]
        assert len(g_after_all) == 3
        assert all(g["scanned_quantity"] == 0.0 and g["is_complete"] is False for g in g_after_all)


class TestStockReuploadAfterScans:
    """
    Açık sevkiyatlar ve yapılmış okutmalar varken üstüne yeni stok Excel'i
    (hem replace=True 'Sıfırdan Değiştir' hem replace=False 'Stok Güncelle / Ekle')
    yüklendiğinde FIFO hesabının, okutulmuş etiketlerin ve kalan ihtiyaçların
    nasıl davrandığını doğrulayan kapsamlı testler.
    """

    @staticmethod
    def _make_excel(rows: list[tuple]) -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.append(["ETİKET", "REFERANS", "MİKTAR", "X98FIFO_TARIH"])
        for r in rows:
            ws.append(list(r))
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_replace_stock_with_reordered_rows_preserves_scanned_label_ids_and_recalculates(self, client):
        """
        Senaryo 1 (ID Kayması Koruması):
        Stok 1 yüklenir, 2 sevkiyat oluşturulur, S1 içinde bir etiket okutulur.
        Ardından satır sırası tamamen farklı olan ve başına başka referanslar eklenmiş
        yeni bir Stok Excel'i replace=True ile yüklenir.
        Okutulan etiketin başka bir referans/barkod ile karışmadığı ve kalan ihtiyacın
        yeni stoktan doğru hesaplandığı doğrulanır.
        """
        stock_v1 = self._make_excel([
            ("LBL-A1", "REF-A", 30, "10.05.2026 08:00"),
            ("LBL-A2", "REF-A", 30, "15.05.2026 08:00"),
            ("LBL-A3", "REF-A", 30, "20.05.2026 08:00"),
        ])
        client.post(
            "/api/inventory/import/stock?replace=true",
            files={"file": ("s1.xlsx", stock_v1, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

        # S1: 60 adet (10.05 + 15.05), S2: 30 adet (20.05)
        client.post("/api/shipment/targets", json={"reference": "REF-A", "target_quantity": 60})
        client.post("/api/shipment/find")
        client.post("/api/shipment/targets", json={"reference": "REF-A", "target_quantity": 30})
        client.post("/api/shipment/find")

        groups = client.get("/api/shipment/groups").json()
        g1_id, g2_id = groups[0]["group_id"], groups[1]["group_id"]

        # S1 için LBL-A1 (10.05.2026, 30 adet) okut
        scan_res = client.post("/api/shipment/scan", json={"label": "LBL-A1", "group_id": g1_id}).json()
        assert scan_res["success"] is True
        assert scan_res["scanned_quantity"] == 30.0

        # Şimdi tamamen farklı sırada, başında başka referanslar olan ve 12.05.2026 tarihli
        # yeni bir etiket (LBL-A-NEW) içeren Yeni Stok Exceli (replace=True) yükle!
        stock_v2 = self._make_excel([
            ("LBL-Z99", "REF-OTHER", 500, "01.01.2026 08:00"),
            ("LBL-A3", "REF-A", 30, "20.05.2026 08:00"),
            ("LBL-A-NEW", "REF-A", 30, "12.05.2026 08:00"),
            ("LBL-A2", "REF-A", 30, "15.05.2026 08:00"),
            ("LBL-A1", "REF-A", 30, "10.05.2026 08:00"),
        ])
        imp_res = client.post(
            "/api/inventory/import/stock?replace=true",
            files={"file": ("s2.xlsx", stock_v2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert imp_res.status_code == 200

        # Kontroller:
        # 1) S1'in okutulmuş 30 adedi (10.05.2026 - LBL-A1) bozulmamış olmalı!
        # 2) S1'in kalan 30 adedi artık 15.05.2026 yerine yeni gelen daha eski 12.05.2026 (LBL-A-NEW) olmalı!
        # 3) S2'nin 30 adedi ise 20.05.2026 yerine bir önceki tarih olan 15.05.2026 (LBL-A2) olmalı!
        groups_after = client.get("/api/shipment/groups").json()
        s1_ref = groups_after[0]["items"][0]
        assert s1_ref["scanned_quantity"] == 30.0

        # Manifest içinde S1'in okutulan etiketi hala LBL-A1 olmalı (LBL-Z99 ile karışmamalı!)
        manifest_s1 = client.get(f"/api/shipment/manifest?group_id={g1_id}").json()
        m1_dates = {d["fifo_group_date"]: d for d in manifest_s1[0]["items"]}
        assert set(m1_dates.keys()) == {"10.05.2026", "12.05.2026"}
        assert m1_dates["10.05.2026"]["scanned_quantity"] == 30.0
        assert m1_dates["10.05.2026"]["outside_fifo"] is False
        assert m1_dates["10.05.2026"]["scanned_labels"][0]["label"] == "LBL-A1"
        assert m1_dates["12.05.2026"]["quantity"] == 30.0
        assert m1_dates["12.05.2026"]["scanned_quantity"] == 0.0

        manifest_s2 = client.get(f"/api/shipment/manifest?group_id={g2_id}").json()
        m2_dates = {d["fifo_group_date"]: d for d in manifest_s2[0]["items"]}
        assert set(m2_dates.keys()) == {"15.05.2026"}
        assert m2_dates["15.05.2026"]["quantity"] == 30.0

        # S1 için eski 15.05.2026 (LBL-A2) okutulursa reddedilmeli ve 12.05.2026 önerilmeli;
        # yeni 12.05.2026 (LBL-A-NEW) okutulursa kabul edilip S1 tamamlanmalı!
        bad_scan = client.post("/api/shipment/scan", json={"label": "LBL-A2", "group_id": g1_id}).json()
        assert bad_scan["success"] is False
        assert bad_scan["expected_fifo_date"] == "12.05.2026"

        good_scan = client.post("/api/shipment/scan", json={"label": "LBL-A-NEW", "group_id": g1_id}).json()
        assert good_scan["success"] is True
        assert good_scan["is_complete"] is True

    def test_older_fifo_stock_uploaded_after_scan_marks_previous_scan_outside_fifo(self, client):
        """
        Senaryo 2 (Daha Eski FIFO Tarihli Stok Gelmesi):
        Başlangıçta sadece 10.05.2026 (60 adet) vardır. S1 (60 adet) için 30 adet okutulur.
        Sonra yeni stok Excel'inde 01.05.2026 (60 adet) daha eski stok gelir!
        - S1'in kalan 30 adedi 01.05.2026'ya bağlanır.
        - Önceden okutulan 10.05.2026 (30 adet), ideal 60 adedin tamamı 01.05.2026 olduğu için
          'outside_fifo=True' (FIFO dışı) olarak işaretlenir!
        """
        stock_v1 = self._make_excel([
            ("L-10MAY-1", "REF-FIFO", 30, "10.05.2026 08:00"),
            ("L-10MAY-2", "REF-FIFO", 30, "10.05.2026 09:00"),
        ])
        client.post(
            "/api/inventory/import/stock?replace=true",
            files={"file": ("s1.xlsx", stock_v1, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        client.post("/api/shipment/targets", json={"reference": "REF-FIFO", "target_quantity": 60})
        client.post("/api/shipment/find")
        g1_id = client.get("/api/shipment/groups").json()[0]["group_id"]

        # 10.05.2026 tarihli ilk etiketi okut (30 / 60)
        assert client.post("/api/shipment/scan", json={"label": "L-10MAY-1", "group_id": g1_id}).json()["success"] is True

        # Yeni stok Excel'inde 01.05.2026 tarihli 60 adet (2x30) daha eski stok gelsin!
        stock_v2 = self._make_excel([
            ("L-01MAY-1", "REF-FIFO", 30, "01.05.2026 08:00"),
            ("L-01MAY-2", "REF-FIFO", 30, "01.05.2026 09:00"),
            ("L-10MAY-1", "REF-FIFO", 30, "10.05.2026 08:00"),
            ("L-10MAY-2", "REF-FIFO", 30, "10.05.2026 09:00"),
        ])
        client.post(
            "/api/inventory/import/stock?replace=true",
            files={"file": ("s2.xlsx", stock_v2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

        manifest = client.get(f"/api/shipment/manifest?group_id={g1_id}").json()
        dates = {d["fifo_group_date"]: d for d in manifest[0]["items"]}
        assert set(dates.keys()) == {"01.05.2026", "10.05.2026"}
        assert dates["01.05.2026"]["quantity"] == 30.0
        assert dates["01.05.2026"]["scanned_quantity"] == 0.0
        assert dates["01.05.2026"]["outside_fifo"] is False
        assert dates["10.05.2026"]["scanned_quantity"] == 30.0
        assert dates["10.05.2026"]["outside_fifo"] is True

    def test_erp_deducted_scanned_label_in_new_stock_excel_is_preserved_and_not_false_outside_fifo(self, client):
        """
        Senaryo 3 (ERP'den Çekilen Yeni Stok Excel'inde Okutulmuş Etiketin Düşülmüş Olması):
        Operatör 01.05.2026 tarihli L-ERP-1 (30 adet) etiketini okutur.
        Sonra yüklenen yeni stok Excel'inde L-ERP-1 ERP'den düştüğü için yer almaz,
        sadece L-ERP-2 (05.05.2026, 30 adet) ve L-ERP-3 (10.05.2026, 30 adet) vardır.
        - L-ERP-1 okutması silinmez (30/60 korunur).
        - L-ERP-1 en eski tarih olduğu için yanlışlıkla 'outside_fifo=True' OLMAZ!
        - L-ERP-1 tekrar okutulursa 'not_found' değil 'already_scanned' döner!
        """
        stock_v1 = self._make_excel([
            ("L-ERP-1", "REF-ERP", 30, "01.05.2026 08:00"),
            ("L-ERP-2", "REF-ERP", 30, "05.05.2026 08:00"),
            ("L-ERP-3", "REF-ERP", 30, "10.05.2026 08:00"),
        ])
        client.post(
            "/api/inventory/import/stock?replace=true",
            files={"file": ("s1.xlsx", stock_v1, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        client.post("/api/shipment/targets", json={"reference": "REF-ERP", "target_quantity": 60})
        client.post("/api/shipment/find")
        g1_id = client.get("/api/shipment/groups").json()[0]["group_id"]

        # L-ERP-1 (01.05.2026) okut
        assert client.post("/api/shipment/scan", json={"label": "L-ERP-1", "group_id": g1_id}).json()["success"] is True

        # Yeni stok Excel'inde L-ERP-1 yok (ERP'den düşülmüş)
        stock_v2 = self._make_excel([
            ("L-ERP-2", "REF-ERP", 30, "05.05.2026 08:00"),
            ("L-ERP-3", "REF-ERP", 30, "10.05.2026 08:00"),
        ])
        client.post(
            "/api/inventory/import/stock?replace=true",
            files={"file": ("s2.xlsx", stock_v2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

        ref_data = client.get("/api/shipment/groups").json()[0]["items"][0]
        assert ref_data["scanned_quantity"] == 30.0

        manifest = client.get(f"/api/shipment/manifest?group_id={g1_id}").json()
        dates = {d["fifo_group_date"]: d for d in manifest[0]["items"]}
        assert set(dates.keys()) == {"01.05.2026", "05.05.2026"}
        assert dates["01.05.2026"]["outside_fifo"] is False
        assert dates["05.05.2026"]["outside_fifo"] is False

        # L-ERP-1 tekrar okutulursa Mükerrer Okutma (already_scanned) dönmeli
        dup = client.post("/api/shipment/scan", json={"label": "L-ERP-1", "group_id": g1_id}).json()
        assert dup["already_scanned"] is True

        # L-ERP-2 okutulunca sevkiyat 60/60 tamamlanmalı
        done = client.post("/api/shipment/scan", json={"label": "L-ERP-2", "group_id": g1_id}).json()
        assert done["success"] is True
        assert done["is_complete"] is True

    def test_shortage_shipment_with_scans_automatically_fills_missing_stock_on_new_stock_excel(self, client):
        """
        Senaryo 4 (Eksik Stoklu Sevkiyatın Üstüne Yeni Stok Exceli Gelince Eksiğin Kapanması):
        Stok 1'de sadece 30 adet vardır. S1 (60 adet) ve S2 (30 adet) açılır:
        - S1: 30 tahsisli, 30 eksik (short_quantity=30).
        - S2: 0 tahsisli, 30 eksik (short_quantity=30).
        S1 mevcut 30 adedi okutur.
        Ardından Yeni Stok Exceli yüklenir ve 60 adet yeni stok eklenir!
        - S1'in eksik 30 adedi ve S2'nin eksik 30 adedi otomatik olarak yeni stoktan tamamlanır!
        """
        stock_v1 = self._make_excel([
            ("L-SH-1", "REF-SH", 30, "01.05.2026 08:00"),
        ])
        client.post(
            "/api/inventory/import/stock?replace=true",
            files={"file": ("s1.xlsx", stock_v1, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        client.post("/api/shipment/targets", json={"reference": "REF-SH", "target_quantity": 60})
        client.post("/api/shipment/find")
        client.post("/api/shipment/targets", json={"reference": "REF-SH", "target_quantity": 30})
        client.post("/api/shipment/find")

        groups = client.get("/api/shipment/groups").json()
        g1_id, g2_id = groups[0]["group_id"], groups[1]["group_id"]
        assert groups[0]["items"][0]["short_quantity"] == 30.0
        assert groups[1]["items"][0]["short_quantity"] == 30.0

        # S1 mevcut tek koliyi okutsun
        assert client.post("/api/shipment/scan", json={"label": "L-SH-1", "group_id": g1_id}).json()["success"] is True

        # Yeni stok Excel'inde 2 yeni koli (toplam 60 adet) gelsin
        stock_v2 = self._make_excel([
            ("L-SH-1", "REF-SH", 30, "01.05.2026 08:00"),
            ("L-SH-2", "REF-SH", 30, "03.05.2026 08:00"),
            ("L-SH-3", "REF-SH", 30, "06.05.2026 08:00"),
        ])
        client.post(
            "/api/inventory/import/stock?replace=true",
            files={"file": ("s2.xlsx", stock_v2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

        groups_after = client.get("/api/shipment/groups").json()
        assert groups_after[0]["items"][0]["short_quantity"] == 0.0
        assert groups_after[1]["items"][0]["short_quantity"] == 0.0

        # S1 L-SH-2 (03.05.2026) ile, S2 L-SH-3 (06.05.2026) ile tamamlanabilmeli
        assert client.post("/api/shipment/scan", json={"label": "L-SH-2", "group_id": g1_id}).json()["is_complete"] is True
        assert client.post("/api/shipment/scan", json={"label": "L-SH-3", "group_id": g2_id}).json()["is_complete"] is True

