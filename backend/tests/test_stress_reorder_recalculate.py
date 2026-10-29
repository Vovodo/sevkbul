"""
Kapsamlı çoklu sevkiyat, yeniden sıralama, yeniden hesaplama, kısmi okutma,
geri alma (undo) ve 20+ referanslı stres testleri.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from io import BytesIO
import time

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
from app.database import Base, get_db
from app.main import app
from app.models import (
    InventoryLabel,
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
    list_candidate_labels,
    undo_scan,
)
from app.services.scan_service import process_global_scan
from app.services.shipment_service import (
    create_shipment_from_reference,
    get_shipment_groups,
    get_shipment_progress,
    recalculate_shipments,
    reorder_shipment_groups,
)
from app.services.target_service import add_target, find_shipments


@pytest.fixture(autouse=True)
def reset_cache():
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


def add_inv(db, label: str, ref: str, qty: float, dt: datetime) -> InventoryLabel:
    row = InventoryLabel(
        label=label,
        reference=ref,
        quantity=Decimal(str(qty)),
        fifo_date=dt,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_shipment_excel(rows: list[tuple[str, float]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["REFERANS", "MİKTAR"])
    for ref, qty in rows:
        ws.append([ref, qty])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_stock_excel(rows: list[tuple[str, str, float, str]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["ETİKET", "REFERANS", "MİKTAR", "X98FIFO_TARIH"])
    for lbl, ref, qty, dt_str in rows:
        ws.append([lbl, ref, qty, dt_str])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestSortOrderZeroCollisionBug:
    """
    Kullanıcının bildirdiği hatanın birebir testi:
    İlk sevkiyat sort_order=0 aldığında, sonraki sevkiyatların sort_order
    değerlerinin çakışmaması ve son sevkiyat en üste taşındığında stoğu
    eksiksiz alması.
    """

    def test_initial_sort_orders_are_strictly_increasing(self, db):
        for i in range(1, 5):
            add_inv(db, f"L-{i}", "REF-X", 100, datetime(2026, 6, i, 8, 0))

        # 4 ayrı sevkiyat grubu oluştur
        for i in range(4):
            add_target(db, "REF-X", Decimal("100"), source_name=f"Sevkiyat-{i+1}")
            find_shipments(db)

        groups = get_shipment_groups(db)
        assert len(groups) == 4
        sort_orders = [
            db.query(Shipment.sort_order).filter(Shipment.group_id == g["group_id"]).scalar()
            for g in groups
        ]
        # Kesinlikle [0, 1, 2, 3] olmalı (eskiden [0, 1, 2, 3] yerine [0, 1, 1, 1] veya [0, 1, 2] çakışması oluyordu)
        assert sort_orders == [0, 1, 2, 3]

    def test_last_shipment_with_exhausted_stock_gets_full_stock_when_moved_to_top(self, db):
        """
        Stokta X referansından 200 adet var.
        1. Sevkiyat: X = 100
        2. Sevkiyat: X = 100
        3. Sevkiyat: X = 100 -> Oluşturulduğunda stok bittiği için 'Eksik' (short_quantity=100) olur!
        Kullanıcı 3. Sevkiyatı en üste (1. sıraya) alır ve yeniden hesaplar.
        Artık 3. Sevkiyat (yeni 1. sıra) 100 stoğun tamamını almalı (short_quantity=0, stock_note=None),
        eski 2. Sevkiyat ise en sona düştüğü için 'Eksik' olmalıdır!
        """
        add_inv(db, "X-1", "REF-X", 50, datetime(2026, 6, 1, 8, 0))
        add_inv(db, "X-2", "REF-X", 50, datetime(2026, 6, 2, 8, 0))
        add_inv(db, "X-3", "REF-X", 50, datetime(2026, 6, 3, 8, 0))
        add_inv(db, "X-4", "REF-X", 50, datetime(2026, 6, 4, 8, 0))

        for idx in range(1, 4):
            add_target(db, "REF-X", Decimal("100"), source_name=f"S{idx}")
            find_shipments(db)

        groups_before = get_shipment_groups(db)
        assert [g["name"] for g in groups_before] == ["S1", "S2", "S3"]
        # Başlangıçta S3'te stok kalmadı -> Eksik
        s3_item_before = groups_before[2]["items"][0]
        assert s3_item_before["short_quantity"] == 100.0
        assert s3_item_before["stock_note"] == "Eksik"

        # Kullanıcı S3'ü en üste taşıyor: [S3, S1, S2]
        reordered = reorder_shipment_groups(
            db,
            [groups_before[2]["group_id"], groups_before[0]["group_id"], groups_before[1]["group_id"]],
        )
        assert [g["name"] for g in reordered] == ["S3", "S1", "S2"]

        # S3 artık 1. sırada ve stoğu tam (short_quantity == 0, stock_note is None)
        s3_item_after = reordered[0]["items"][0]
        assert s3_item_after["short_quantity"] == 0.0
        assert s3_item_after["stock_note"] is None

        # S3 en eski FIFO tarihlerini (01.06 ve 02.06) almış olmalı
        manifests = {m["shipment_id"]: m for m in get_shipment_manifest(db)}
        s3_dates = [it["fifo_group_date"] for it in manifests[s3_item_after["shipment_id"]]["items"]]
        assert s3_dates == ["01.06.2026", "02.06.2026"]

        # S1 artık 2. sırada ve sonraki FIFO tarihlerini (03.06 ve 04.06) almış olmalı
        s1_item_after = reordered[1]["items"][0]
        assert s1_item_after["short_quantity"] == 0.0
        s1_dates = [it["fifo_group_date"] for it in manifests[s1_item_after["shipment_id"]]["items"]]
        assert s1_dates == ["03.06.2026", "04.06.2026"]

        # S2 artık 3. sırada ve stok kalmadığı için Eksik olmalı
        s2_item_after = reordered[2]["items"][0]
        assert s2_item_after["short_quantity"] == 100.0
        assert s2_item_after["stock_note"] == "Eksik"


class TestMultiShipment20ReferencesStress:
    """
    4 ayrı sevkiyat, her birinde 20 farklı referans (toplam 80 sevkiyat kalemi).
    Bazı referanslar tüm sevkiyatlarda ortak, bazıları kısmi stoklu, bazıları tam stoklu.
    """

    def test_4_shipments_each_with_20_references_reorder_and_recalculate(self, db):
        # 25 farklı referans için stok oluştur:
        # Her referansta 5 gün × 2 etiket × 30 adet = 300 adet stok var.
        base_dt = datetime(2026, 6, 1, 8, 0)
        for r_idx in range(1, 26):
            ref = f"REF-{r_idx:03d}"
            for day in range(5):
                for box in range(2):
                    lbl = f"LBL-{r_idx:03d}-D{day}-B{box}"
                    add_inv(db, lbl, ref, 30, base_dt + timedelta(days=day, hours=box))

        # 4 sevkiyat oluştur; her sevkiyatta 20 referans var ve her referanstan 90 adet isteniyor.
        # Toplam 4 × 90 = 360 adet talep > 300 adet stok!
        # Dolayısıyla:
        # - Sıradaki 1. sevkiyat: 90 alır (Eksik: 0) -> Gün 0 (60) + Gün 1 (30)
        # - Sıradaki 2. sevkiyat: 90 alır (Eksik: 0) -> Gün 1 (30) + Gün 2 (60)
        # - Sıradaki 3. sevkiyat: 90 alır (Eksik: 0) -> Gün 3 (60) + Gün 4 (30)
        # - Sıradaki 4. sevkiyat: sadece 30 alabilir (Eksik: 60) -> Gün 4 (30)
        shipment_refs = [
            [f"REF-{i:03d}" for i in range(1, 21)],   # S1: REF-001 .. REF-020
            [f"REF-{i:03d}" for i in range(1, 21)],   # S2: REF-001 .. REF-020
            [f"REF-{i:03d}" for i in range(1, 21)],   # S3: REF-001 .. REF-020
            [f"REF-{i:03d}" for i in range(1, 21)],   # S4: REF-001 .. REF-020
        ]

        for s_idx, refs in enumerate(shipment_refs, start=1):
            for ref in refs:
                add_target(db, ref, Decimal("90"), source_name=f"Sevkiyat-{s_idx}")
            find_shipments(db)

        groups = get_shipment_groups(db)
        assert len(groups) == 4
        for g in groups:
            assert len(g["items"]) == 20

        # İlk durumda S1, S2, S3 tam (short=0), S4'teki tüm 20 referans 60 eksik olmalı
        for idx in range(3):
            assert all(it["short_quantity"] == 0 for it in groups[idx]["items"])
        assert all(it["short_quantity"] == 60 for it in groups[3]["items"])

        g1, g2, g3, g4 = [g["group_id"] for g in groups]

        # ŞİMDİ: S4'ü 1. sıraya, S3'ü 2. sıraya, S2'yi 3. sıraya, S1'i 4. sıraya alalım!
        new_order = [g4, g3, g2, g1]
        groups_after = reorder_shipment_groups(db, new_order)
        assert [g["group_id"] for g in groups_after] == new_order

        # Tekrar recalculate_shipments çağrıldığında da sonuç %100 aynı ve kararlı kalmalı
        recalculate_shipments(db)
        groups_after_recalc = get_shipment_groups(db)
        assert [g["group_id"] for g in groups_after_recalc] == new_order

        # Artık yeni 1., 2., 3. sıradaki (g4, g3, g2) sevkiyatların 20 referansının tamamı 0 eksik olmalı!
        for pos in range(3):
            for item in groups_after_recalc[pos]["items"]:
                assert item["short_quantity"] == 0, f"Pos {pos} ref {item['reference']} has short {item['short_quantity']}"
                assert item["stock_note"] is None

        # En sona düşen g1'in 20 referansının tamamı 60 eksik olmalı!
        for item in groups_after_recalc[3]["items"]:
            assert item["short_quantity"] == 60
            assert item["stock_note"] is None  # kısmi stok (30/90) olduğu için tamamen stoksuz değil

        # Manifest tarihlerini kontrol et:
        # 1. sıradaki g4 en eski tarihleri (01.06 ve 02.06) almış olmalı
        manifests = {m["shipment_id"]: m for m in get_shipment_manifest(db)}
        for item in groups_after_recalc[0]["items"]:
            m = manifests[item["shipment_id"]]
            dates = [(i["fifo_group_date"], i["quantity"]) for i in m["items"]]
            assert dates == [("01.06.2026", 60.0), ("02.06.2026", 30.0)]

        # 2. sıradaki g3: 02.06 (30) ve 03.06 (60) almış olmalı
        for item in groups_after_recalc[1]["items"]:
            m = manifests[item["shipment_id"]]
            dates = [(i["fifo_group_date"], i["quantity"]) for i in m["items"]]
            assert dates == [("02.06.2026", 30.0), ("03.06.2026", 60.0)]

        # 3. sıradaki g2: 04.06 (60) ve 05.06 (30) almış olmalı
        for item in groups_after_recalc[2]["items"]:
            m = manifests[item["shipment_id"]]
            dates = [(i["fifo_group_date"], i["quantity"]) for i in m["items"]]
            assert dates == [("04.06.2026", 60.0), ("05.06.2026", 30.0)]

        # 4. sıradaki g1: sadece 05.06 (30) alabilmiş olmalı
        for item in groups_after_recalc[3]["items"]:
            m = manifests[item["shipment_id"]]
            dates = [(i["fifo_group_date"], i["quantity"]) for i in m["items"]]
            assert dates == [("05.06.2026", 30.0)]


class TestComplexScansReorderUndoAndRecalculate:
    """
    Okutma + Yeniden Sıralama + Geri Alma (Undo) + Sevkiyat Silme + Excel Birleştirme
    karma senaryoları.
    """

    def test_duplicate_references_in_same_shipment_excel_are_merged(self, client):
        stock = make_stock_excel([
            ("E-1", "REF-DUP", 50, "01.06.2026 08:00"),
            ("E-2", "REF-DUP", 50, "02.06.2026 08:00"),
            ("E-3", "REF-DUP", 50, "03.06.2026 08:00"),
        ])
        res = client.post(
            "/api/inventory/import/stock",
            files={"file": ("stok.xlsx", stock, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert res.status_code == 200

        # Aynı Excel içinde REF-DUP iki kez geçiyor (40 + 60 = 100)
        ship_xlsx = make_shipment_excel([
            ("REF-DUP", 40),
            ("OTHER-1", 20),
            ("ref-dup ", 60),
        ])
        imp = client.post(
            "/api/shipment/targets/import",
            files={"file": ("Sevkiyat1.xlsx", ship_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert imp.status_code == 200
        targets = client.get("/api/shipment/targets").json()
        assert len(targets) == 2
        dup_target = next(t for t in targets if t["reference"].upper() == "REF-DUP")
        assert dup_target["target_quantity"] == 100.0

        found = client.post("/api/shipment/find")
        assert found.status_code == 200
        groups = client.get("/api/shipment/groups").json()
        assert len(groups) == 1
        assert len(groups[0]["items"]) == 2
        dup_item = next(it for it in groups[0]["items"] if it["reference"] == "REF-DUP")
        assert dup_item["requested_quantity"] == 100.0
        assert dup_item["short_quantity"] == 0.0

    def test_scans_preserved_across_multiple_reorders_and_outside_fifo_flagged_correctly(self, db):
        # 4 gün × 30 adet = 120 adet stok
        l1 = add_inv(db, "L1", "REF-A", 30, datetime(2026, 6, 1, 8, 0))
        l2 = add_inv(db, "L2", "REF-A", 30, datetime(2026, 6, 2, 8, 0))
        l3 = add_inv(db, "L3", "REF-A", 30, datetime(2026, 6, 3, 8, 0))
        l4 = add_inv(db, "L4", "REF-A", 30, datetime(2026, 6, 4, 8, 0))

        # S1: 60 adet (01.06, 02.06)
        # S2: 60 adet (03.06, 04.06)
        add_target(db, "REF-A", Decimal("60"), source_name="S1")
        find_shipments(db)
        add_target(db, "REF-A", Decimal("60"), source_name="S2")
        find_shipments(db)

        groups = get_shipment_groups(db)
        g1_id, g2_id = groups[0]["group_id"], groups[1]["group_id"]
        s1_id = groups[0]["items"][0]["shipment_id"]
        s2_id = groups[1]["items"][0]["shipment_id"]

        # S2'de 04.06 tarihli L4 etiketini okut
        scan_res = process_global_scan(db, "L4", target_group_id=g2_id)
        assert scan_res.success is True
        assert scan_res.result == "SEVKİYAT ÜRÜNÜ"

        # Şu an S2'de 04.06 FIFO dışı DEĞİL çünkü S1 (01.06, 02.06) önde duruyor
        m_before = {m["shipment_id"]: m for m in get_shipment_manifest(db)}
        s2_items_before = {i["fifo_group_date"]: i for i in m_before[s2_id]["items"]}
        assert s2_items_before["04.06.2026"]["outside_fifo"] is False

        # Şimdi S2'yi S1'in önüne taşı! (S2 artık 1. sırada, ideal tarihleri 01.06 ve 02.06 oldu)
        reorder_shipment_groups(db, [g2_id, g1_id])

        m_after = {m["shipment_id"]: m for m in get_shipment_manifest(db)}
        s2_items_after = {i["fifo_group_date"]: i for i in m_after[s2_id]["items"]}
        # S2'nin kalan 30 adedi en eski tarih olan 01.06'dan alındı, 04.06'daki okutma ise FIFO dışı olarak işaretlendi!
        assert "01.06.2026" in s2_items_after
        assert s2_items_after["01.06.2026"]["quantity"] == 30.0
        assert s2_items_after["04.06.2026"]["scanned_quantity"] == 30.0
        assert s2_items_after["04.06.2026"]["outside_fifo"] is True

        # S1 ise artık 2. sırada: kalan 60 adedini 02.06 (30) ve 03.06 (30) tarihlerinden alır!
        s1_items_after = {i["fifo_group_date"]: i for i in m_after[s1_id]["items"]}
        assert list(s1_items_after.keys()) == ["02.06.2026", "03.06.2026"]

        # Şimdi S2'deki L4 okutmasını geri al (undo) ve yeniden hesapla
        undo_scan(db, s2_id, "L4")
        recalculate_shipments(db)

        m_undo = {m["shipment_id"]: m for m in get_shipment_manifest(db)}
        s2_items_undo = {i["fifo_group_date"]: i for i in m_undo[s2_id]["items"]}
        s1_items_undo = {i["fifo_group_date"]: i for i in m_undo[s1_id]["items"]}
        # S2 (1. sıra): 01.06 (30) ve 02.06 (30)
        assert list(s2_items_undo.keys()) == ["01.06.2026", "02.06.2026"]
        # S1 (2. sıra): 03.06 (30) ve 04.06 (30)
        assert list(s1_items_undo.keys()) == ["03.06.2026", "04.06.2026"]

    def test_boundary_split_across_3_shipments_and_permutations(self, db):
        """
        Aynı günde 3 etiket × 40 adet = 120 adet stok var (01.06.2026).
        İkinci günde 2 etiket × 40 adet = 80 adet stok var (02.06.2026).
        Toplam = 200 adet.
        3 sevkiyat:
          S1 = 50 adet
          S2 = 50 adet
          S3 = 100 adet
        Tüm 6 permütasyonda (3! = 6 sıra) yeniden sıralama yapıldığında:
        - Toplam tahsis her zaman 200 olmalı (hiçbir sevkiyatta eksik çıkmamalı).
        - Hiçbir sevkiyatın tarih kotası toplamı kendi talep miktarını aşmamalı.
        """
        add_inv(db, "B1", "REF-SPLIT", 40, datetime(2026, 6, 1, 8, 0))
        add_inv(db, "B2", "REF-SPLIT", 40, datetime(2026, 6, 1, 9, 0))
        add_inv(db, "B3", "REF-SPLIT", 40, datetime(2026, 6, 1, 10, 0))
        add_inv(db, "B4", "REF-SPLIT", 40, datetime(2026, 6, 2, 8, 0))
        add_inv(db, "B5", "REF-SPLIT", 40, datetime(2026, 6, 2, 9, 0))

        for name, qty in [("S1", 50), ("S2", 50), ("S3", 100)]:
            add_target(db, "REF-SPLIT", Decimal(str(qty)), source_name=name)
            find_shipments(db)

        groups = get_shipment_groups(db)
        gids = [g["group_id"] for g in groups]

        import itertools
        for perm in itertools.permutations(gids):
            reordered = reorder_shipment_groups(db, list(perm))
            assert [g["group_id"] for g in reordered] == list(perm)
            for g in reordered:
                item = g["items"][0]
                assert item["short_quantity"] == 0.0
                assert item["stock_note"] is None

            manifests = {m["group_id"]: m for m in get_shipment_manifest(db)}
            day1_total = sum(
                it["quantity"]
                for m in manifests.values()
                for it in m["items"]
                if it["fifo_group_date"] == "01.06.2026"
            )
            day2_total = sum(
                it["quantity"]
                for m in manifests.values()
                for it in m["items"]
                if it["fifo_group_date"] == "02.06.2026"
            )
            assert day1_total == 120.0
            assert day2_total == 80.0

    def test_hourly_and_daily_mixed_shipments_reorder(self, db):
        """
        Aynı referans için bir sevkiyat saat öncelikli (hourly_fifo=True),
        diğeri gün öncelikli (hourly_fifo=False) olduğunda sıralama değişimi.
        """
        add_inv(db, "H1", "REF-MIX", 30, datetime(2026, 6, 1, 8, 15))
        add_inv(db, "H2", "REF-MIX", 30, datetime(2026, 6, 1, 14, 45))
        add_inv(db, "H3", "REF-MIX", 30, datetime(2026, 6, 2, 9, 0))

        create_shipment_from_reference(db, "REF-MIX", Decimal("30"), hourly_fifo=True, group_id=1, group_name="Saatli")
        create_shipment_from_reference(db, "REF-MIX", Decimal("60"), hourly_fifo=False, group_id=2, group_name="Gunluk")

        # Sırayı değiştir: Gunluk (60) öne, Saatli (30) arkaya
        reorder_shipment_groups(db, [2, 1])

        manifests = {m["group_id"]: m for m in get_shipment_manifest(db)}
        # Gunluk (60) -> 01.06.2026 günündeki 60 adedin tamamını alır
        assert [(i["fifo_group_date"], i["quantity"]) for i in manifests[2]["items"]] == [("01.06.2026", 60.0)]
        # Saatli (30) -> 02.06.2026 09:00 etiketini alır
        assert [(i["fifo_group_date"], i["quantity"]) for i in manifests[1]["items"]] == [("02.06.2026 09:00", 30.0)]

    def test_delete_middle_shipment_and_recalculate_recovers_stock_for_bottom(self, db):
        """
        4 sevkiyat var, 4. sevkiyat stok yetmediği için Eksik.
        Aradaki 2. sevkiyat silinip yeniden hesaplandığında (veya 4. sevkiyat yukarı taşındığında)
        4. sevkiyatın stoğu eksiksiz tamamlanmalı.
        """
        for d in range(1, 4):
            add_inv(db, f"D-{d}", "REF-DEL", 50, datetime(2026, 6, d, 8, 0))

        for idx in range(1, 5):
            add_target(db, "REF-DEL", Decimal("50"), source_name=f"G{idx}")
            find_shipments(db)

        groups = get_shipment_groups(db)
        assert groups[3]["items"][0]["short_quantity"] == 50.0
        assert groups[3]["items"][0]["stock_note"] == "Eksik"

        # G2'yi sil ve yeniden hesapla
        delete_shipment_group(db, groups[1]["group_id"])
        recalculate_shipments(db)

        after = get_shipment_groups(db)
        assert len(after) == 3
        for g in after:
            assert g["items"][0]["short_quantity"] == 0.0
            assert g["items"][0]["stock_note"] is None


class TestNewOperatorFeatures:
    """
    1. Yanlış etiket okutulduğunda beklenen FIFO tarihi ve uygun sevkiyat yönlendirmesi
    2. Excel / İrsaliye çıktısı (3 sayfalı .xlsx raporu)
    5. Stok güncelleme / üzerine ekleme (upsert, mevcut okutmaları bozmadan)
    """

    def test_wrong_label_scan_returns_expected_fifo_and_suggested_shipment(self, client):
        stock = make_stock_excel([
            ("LBL-OLD", "REF-HINT", 30, "10.06.2026 08:00"),
            ("LBL-NEW", "REF-HINT", 30, "25.07.2026 08:00"),
        ])
        client.post(
            "/api/inventory/import/stock",
            files={"file": ("s.xlsx", stock, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        # 1. Sevkiyat: 30 adet (10.06.2026 alır)
        client.post("/api/shipment/targets", json={"reference": "REF-HINT", "target_quantity": 30})
        client.post("/api/shipment/find")
        # 2. Sevkiyat: 30 adet (25.07.2026 alır)
        client.post("/api/shipment/targets", json={"reference": "REF-HINT", "target_quantity": 30})
        client.post("/api/shipment/find")

        groups = client.get("/api/shipment/groups").json()
        g1_id = groups[0]["group_id"]

        # 1. Sevkiyat seçiliyken 25.07.2026 tarihli LBL-NEW okutulursa:
        res = client.post("/api/shipment/scan", json={"label": "LBL-NEW", "group_id": g1_id})
        assert res.status_code == 200
        data = res.json()
        assert data["result"] == "SEVKİYAT DIŞI"
        assert data["expected_fifo_date"] == "10.06.2026"
        assert data["suggested_shipment"] == groups[1]["name"]
        assert "10.06.2026" in (data["hint"] or "")
        assert groups[1]["name"] in (data["hint"] or "")

    def test_stock_append_upserts_existing_labels_and_keeps_active_scans(self, client):
        stock1 = make_stock_excel([
            ("LBL-1", "REF-UP", 30, "01.06.2026 08:00"),
        ])
        client.post(
            "/api/inventory/import/stock?replace=true",
            files={"file": ("s1.xlsx", stock1, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        client.post("/api/shipment/targets", json={"reference": "REF-UP", "target_quantity": 60})
        client.post("/api/shipment/find")

        # Başlangıçta 30 eksik
        g_before = client.get("/api/shipment/groups").json()
        assert g_before[0]["items"][0]["short_quantity"] == 30.0

        # LBL-1'i okut
        scan = client.post("/api/shipment/scan", json={"label": "LBL-1"})
        assert scan.json()["result"] == "SEVKİYAT ÜRÜNÜ"

        # Şimdi hem LBL-1'i hem de yeni LBL-2'yi içeren tam stok Excel'ini replace=false ile yükle!
        # UNIQUE constraint hatası vermemeli ve LBL-2'yi eklemeli.
        stock2 = make_stock_excel([
            ("LBL-1", "REF-UP", 30, "01.06.2026 08:00"),
            ("LBL-2", "REF-UP", 30, "02.06.2026 08:00"),
        ])
        up = client.post(
            "/api/inventory/import/stock?replace=false",
            files={"file": ("s2.xlsx", stock2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert up.status_code == 200
        assert up.json()["successful"] == 2

        # Yeniden hesapla
        client.post("/api/shipment/recalculate")
        for _ in range(50):
            st = client.get("/api/shipment/recalculate/status").json()
            if st["phase"] in ("done", "idle"):
                break
            time.sleep(0.05)

        g_after = client.get("/api/shipment/groups").json()
        assert g_after[0]["items"][0]["scanned_quantity"] == 30.0
        assert g_after[0]["items"][0]["short_quantity"] == 0.0

    def test_export_manifest_excel_endpoint_returns_valid_workbook(self, client):
        from openpyxl import load_workbook

        stock = make_stock_excel([
            ("EXP-1", "REF-EXP", 45, "05.06.2026 08:00"),
        ])
        client.post(
            "/api/inventory/import/stock",
            files={"file": ("s.xlsx", stock, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        client.post("/api/shipment/targets", json={"reference": "REF-EXP", "target_quantity": 45})
        client.post("/api/shipment/find")
        client.post("/api/shipment/scan", json={"label": "EXP-1"})

        resp = client.get("/api/shipment/export")
        assert resp.status_code == 200
        wb = load_workbook(BytesIO(resp.content))
        assert wb.sheetnames == ["Sevkiyat Özeti", "Okutulan Etiketler", "FIFO Tarih Planı"]
        ws_labels = wb["Okutulan Etiketler"]
        rows = list(ws_labels.iter_rows(values_only=True))
        assert len(rows) == 2
        assert rows[1][1] == "REF-EXP"
        assert rows[1][2] == "EXP-1"
        assert rows[1][3] == 45


class TestBlokajFeature:
    """
    BLOKAJ sütunu (YANLIŞ=blokajsız, DOĞRU=blokajlı):
    - Referans bazında kaç blokajlı / kaç blokajsız etiket olduğunun görünmesi
    - Normal modda (blocked_only=False) sadece FIFO blokajsız etiketlerin okunması, blokajlıların reddedilmesi
    - 'Sadece Blokajlıları Oku' modunda (blocked_only=True) sadece seçili sevkiyattaki referansların
      blokajlı etiketlerinin okunması; blokajsızların (sevkiyatta olsa bile) ve sevkiyat dışı
      referansların blokajlı etiketlerinin reddedilmesi
    - Gerçek 'Bergama REFERANS STOK 3.xlsx' dosyasının import ve blokaj doğrulaması
    """

    def test_blokaj_counts_and_blocked_only_scan_mode(self, client):
        wb = Workbook()
        ws = wb.active
        ws.append(["ETİKET", "REFERANS", "MİKTAR", "X98FIFO_TARIH", "BLOKAJ"])
        # REF-1: 2 blokajsız (YANLIŞ), 1 blokajlı (DOĞRU)
        ws.append(["BLK-101", "REF-1", 30, "01.06.2026 08:00", "DOĞRU"])
        ws.append(["UNB-102", "REF-1", 30, "02.06.2026 08:00", "YANLIŞ"])
        ws.append(["UNB-103", "REF-1", 30, "03.06.2026 08:00", False])
        # REF-OTHER (sevkiyatta olmayan referans): 1 blokajlı
        ws.append(["BLK-999", "REF-OTHER", 25, "01.06.2026 08:00", True])
        buf = BytesIO()
        wb.save(buf)

        res = client.post(
            "/api/inventory/import/stock",
            files={"file": ("stok.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert res.status_code == 200

        # Sadece REF-1 için 60 adetlik sevkiyat aç
        client.post("/api/shipment/targets", json={"reference": "REF-1", "target_quantity": 60})
        client.post("/api/shipment/find")

        groups = client.get("/api/shipment/groups").json()
        assert len(groups) == 1
        g1 = groups[0]
        ref_item = g1["items"][0]
        assert ref_item["reference"] == "REF-1"
        assert ref_item["blocked_label_count"] == 1
        assert ref_item["unblocked_label_count"] == 2
        assert ref_item["short_quantity"] == 0.0

        # 1. Normal mod (blocked_only=False): Blokajlı etiket (BLK-101) de FIFO içinde olduğu için okutulabilir (okutmaya engel değildir)!
        # Önce blokajsız UNB-102'yi normal modda okutalım:
        s_unb_normal = client.post(
            "/api/shipment/scan",
            json={"label": "UNB-102", "group_id": g1["group_id"], "blocked_only": False},
        ).json()
        assert s_unb_normal["success"] is True
        assert s_unb_normal["result"] == "SEVKİYAT ÜRÜNÜ"

        # 2. 'Sadece Blokajlıları Oku' modu AÇIK (blocked_only=True):
        # Sevkiyat içinde olsa bile blokajsız etiket (UNB-103) REDDEDİLMELİ!
        s_unb_in_blk_mode = client.post(
            "/api/shipment/scan",
            json={"label": "UNB-103", "group_id": g1["group_id"], "blocked_only": True},
        ).json()
        assert s_unb_in_blk_mode["success"] is False
        assert s_unb_in_blk_mode["result"] == "BLOKAJLI DEĞİL"

        # 3. 'Sadece Blokajlıları Oku' modu AÇIK (blocked_only=True):
        # Stokta blokajlı olan ama bu sevkiyatta OLMAYAN referansın etiketi (BLK-999) REDDEDİLMELİ!
        s_other_blk = client.post(
            "/api/shipment/scan",
            json={"label": "BLK-999", "group_id": g1["group_id"], "blocked_only": True},
        ).json()
        assert s_other_blk["success"] is False
        assert s_other_blk["result"] == "SEVKİYAT DIŞI"

        # 4. Blokajlı etiket (BLK-101) hem normal modda hem blokaj modunda KABUL EDİLMELİ!
        s_blk_in_blk_mode = client.post(
            "/api/shipment/scan",
            json={"label": "BLK-101", "group_id": g1["group_id"], "blocked_only": True},
        ).json()
        assert s_blk_in_blk_mode["success"] is True
        assert s_blk_in_blk_mode["result"] == "SEVKİYAT ÜRÜNÜ"
        assert s_blk_in_blk_mode["scanned_quantity"] == 60.0

    def test_real_bergama_referans_stok_3_excel_blokaj_integration(self, client):
        from pathlib import Path

        excel_path = Path(__file__).resolve().parents[2] / "Bergama REFERANS STOK 3.xlsx"
        if not excel_path.exists():
            pytest.skip("Bergama REFERANS STOK 3.xlsx bulunamadı")

        content = excel_path.read_bytes()
        res = client.post(
            "/api/inventory/import/stock",
            files={"file": ("Bergama REFERANS STOK 3.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert res.status_code == 200
        stats = client.get("/api/inventory/stats").json()
        assert stats["blocked_labels"] == 2
        assert stats["unblocked_labels"] == stats["total_labels"] - 2

        # Blokajlı etiketi olan 6681344-HZE-1 (toplam stok 277) ve 6681345-HZE-1 (toplam stok 325) için tam sevkiyat aç
        client.post("/api/shipment/targets", json={"reference": "6681344-HZE-1", "target_quantity": 277})
        client.post("/api/shipment/targets", json={"reference": "6681345-HZE-1", "target_quantity": 325})
        client.post("/api/shipment/find")

        groups = client.get("/api/shipment/groups").json()
        items_by_ref = {it["reference"]: it for it in groups[0]["items"]}
        assert items_by_ref["6681344-HZE-1"]["blocked_label_count"] == 1
        assert items_by_ref["6681344-HZE-1"]["unblocked_label_count"] == 9
        assert items_by_ref["6681344-HZE-1"]["short_quantity"] == 0.0
        assert items_by_ref["6681345-HZE-1"]["blocked_label_count"] == 1
        assert items_by_ref["6681345-HZE-1"]["unblocked_label_count"] == 10
        assert items_by_ref["6681345-HZE-1"]["short_quantity"] == 0.0

        # 6681344-HZE-1 referansının FIFO tarih listesinde 20.07.2026 normal kota (7) ve has_blocked=True olmalı
        sid_344 = items_by_ref["6681344-HZE-1"]["shipment_id"]
        manifests = {m["shipment_id"]: m for m in client.get("/api/shipment/manifest").json()}
        items_344 = {it["fifo_group_date"]: it for it in manifests[sid_344]["items"]}
        assert "20.07.2026" in items_344
        assert items_344["20.07.2026"]["quantity"] == 7.0
        assert items_344["20.07.2026"]["has_blocked"] is True
        cands = client.get(f"/api/shipment/{sid_344}/candidates?fifo_group=20.07.2026").json()
        assert any(l["label"] == "700024406" and l["blocked"] is True for l in cands["labels"])


class TestHighSpeedScanningAndFifoAccuracy:
    """
    1. Her okutma sonrası yeniden hesaplama yapmadan tarih kotasının (ShipmentDateQuota)
       ve ilerlemenin kusursuz çalıştığının doğrulanması.
    2. 100+ referanslı ağır sevkiyat ortamında arka arkaya seri okutma hız testi (benchmark).
    """

    def test_continuous_scanning_without_recalculation_maintains_exact_fifo_quotas(self, db):
        # 3 farklı günde 6 etiket (her gün 2 etiket × 30 adet = 60 adet, toplam 180 adet)
        add_inv(db, "D1-A", "REF-FAST", 30, datetime(2026, 6, 1, 8, 0))
        add_inv(db, "D1-B", "REF-FAST", 30, datetime(2026, 6, 1, 10, 0))
        add_inv(db, "D2-A", "REF-FAST", 30, datetime(2026, 6, 2, 8, 0))
        add_inv(db, "D2-B", "REF-FAST", 30, datetime(2026, 6, 2, 10, 0))
        add_inv(db, "D3-A", "REF-FAST", 30, datetime(2026, 6, 3, 8, 0))
        add_inv(db, "D3-B", "REF-FAST", 30, datetime(2026, 6, 3, 10, 0))

        # S1: 90 adet (01.06 -> 60 adet, 02.06 -> 30 adet)
        # S2: 90 adet (02.06 -> 30 adet, 03.06 -> 60 adet)
        add_target(db, "REF-FAST", Decimal("90"), source_name="S1")
        find_shipments(db)
        add_target(db, "REF-FAST", Decimal("90"), source_name="S2")
        find_shipments(db)

        groups = get_shipment_groups(db)
        g1_id, g2_id = groups[0]["group_id"], groups[1]["group_id"]

        # Hiç recalculate çağırmadan arka arkaya okutmalar yapıyoruz:
        # 1) S1'de D2-B (02.06'nın 2. etiketi) okutuldu -> kabul edilmeli (02.06 kotası 30 doldu!)
        r1 = process_global_scan(db, "D2-B", target_group_id=g1_id)
        assert r1.success is True
        assert r1.scanned_quantity == 30.0

        # 2) S1'de D2-A (02.06'nın diğer etiketi) okutulursa -> S1'in 02.06 kotası (30) dolduğu için MİKTAR AŞILDI dönmeli!
        r2 = process_global_scan(db, "D2-A", target_group_id=g1_id)
        assert r2.success is False
        assert r2.result == "MİKTAR AŞILDI"

        # 3) Ama aynı D2-A etiketi S2'de okutulursa -> S2'nin 02.06 kotası (30) açık olduğu için ANINDA KABUL EDİLMELİ!
        r3 = process_global_scan(db, "D2-A", target_group_id=g2_id)
        assert r3.success is True
        assert r3.scanned_quantity == 30.0

        # 4) S1'in kalan 60 adedini (D1-A ve D1-B) okutarak S1'i tamamla (hiç recalculate yapmadan)
        r4 = process_global_scan(db, "D1-A", target_group_id=g1_id)
        r5 = process_global_scan(db, "D1-B", target_group_id=g1_id)
        assert r4.success is True
        assert r5.success is True
        assert r5.is_complete is True
        assert r5.scanned_quantity == 90.0

    def test_high_speed_rapid_scanning_benchmark_under_heavy_load(self, client):
        # 50 farklı referans, her referansta 4 etiket = 200 etiket ve 50 kalemli sevkiyat
        stock_rows = []
        ship_rows = []
        for r_idx in range(1, 51):
            ref = f"REF-BENCH-{r_idx:03d}"
            ship_rows.append((ref, 60))
            for b_idx in range(1, 5):
                stock_rows.append((f"BENCH-{r_idx:03d}-{b_idx}", ref, 30, f"0{b_idx}.06.2026 08:00"))

        stock_bytes = make_stock_excel(stock_rows)
        ship_bytes = make_shipment_excel(ship_rows)

        client.post(
            "/api/inventory/import/stock",
            files={"file": ("stok.xlsx", stock_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        client.post(
            "/api/shipment/targets/import",
            files={"file": ("sevkiyat.xlsx", ship_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        client.post("/api/shipment/find")

        # 50 etiketi arka arkaya HTTP endpoint üzerinden okut ve süreyi ölç
        t0 = time.perf_counter()
        for r_idx in range(1, 51):
            res = client.post("/api/shipment/scan", json={"label": f"BENCH-{r_idx:03d}-1"})
            assert res.status_code == 200
            assert res.json()["success"] is True
        elapsed = time.perf_counter() - t0
        avg_ms = (elapsed / 50) * 1000
        print(f"\n[BENCHMARK] 50 seri okutma toplam: {elapsed:.3f}s | Ortalama okutma süresi: {avg_ms:.2f} ms")
        # 50 kalemli sevkiyatta dahi ortalama okutma süresi 35 ms'nin çok altında olmalı
        assert avg_ms < 35.0


class TestInventoryHiddenLabelsFeature:
    """
    Stok Listesi menüsünden etiket gizleme (hidden=True) ve tekrar aktif etme (hidden=False):
    - İçerik bilgileri değişmez, yalnızca hidden durumu güncellenir.
    - Gizlenen etiket sevkiyat FIFO hesabından çıkarılır, açık sevkiyatlar otomatik yeniden hesaplanır.
    - Gizlenen etiket okutulmak istenirse kabul edilmez.
    - Tekrar aktif edildiğinde FIFO hesabına geri girer.
    """

    def test_hide_and_unhide_inventory_label_updates_fifo_and_blocks_scan(self, client):
        stock = make_stock_excel([
            ("HID-1", "REF-HID", 30, "01.06.2026 08:00"),
            ("HID-2", "REF-HID", 30, "02.06.2026 08:00"),
        ])
        client.post(
            "/api/inventory/import/stock",
            files={"file": ("stok.xlsx", stock, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        client.post("/api/shipment/targets", json={"reference": "REF-HID", "target_quantity": 30})
        client.post("/api/shipment/find")

        # Başlangıçta 01.06.2026 (HID-1) FIFO havuzunda
        m_before = client.get("/api/shipment/manifest").json()[0]
        assert [it["fifo_group_date"] for it in m_before["items"]] == ["01.06.2026"]

        # Stok listesinden HID-1'i bul ve Gizliye Al (hidden=True)
        inv_list = client.get("/api/inventory/labels?q=HID-1").json()
        assert inv_list["total"] == 2
        hid1_id = inv_list["items"][0]["id"]

        patched = client.patch(f"/api/inventory/labels/{hid1_id}/hidden", json={"hidden": True})
        assert patched.status_code == 200
        assert patched.json()["hidden"] is True

        # Açık sevkiyat otomatik yeniden hesaplanmalı ve artık 02.06.2026 (HID-2) FIFO havuzuna girmeli!
        m_after_hide = client.get("/api/shipment/manifest").json()[0]
        assert [it["fifo_group_date"] for it in m_after_hide["items"]] == ["02.06.2026"]

        # Gizlenen HID-1 okutulmak istenirse reddedilmeli
        scan_hidden = client.post("/api/shipment/scan", json={"label": "HID-1"}).json()
        assert scan_hidden["success"] is False

        # HID-1 tekrar aktif edildiğinde (hidden=False) 01.06.2026 tekrar FIFO havuzuna dönmeli
        unpatched = client.patch(f"/api/inventory/labels/{hid1_id}/hidden", json={"hidden": False})
        assert unpatched.status_code == 200
        assert unpatched.json()["hidden"] is False

        m_after_unhide = client.get("/api/shipment/manifest").json()[0]
        assert [it["fifo_group_date"] for it in m_after_unhide["items"]] == ["01.06.2026"]

    def test_bulk_hide_and_bulk_unhide_labels(self, client):
        stock = make_stock_excel([
            ("BLK-H1", "REF-BULK", 20, "01.06.2026 08:00"),
            ("BLK-H2", "REF-BULK", 20, "02.06.2026 08:00"),
            ("BLK-H3", "REF-BULK", 20, "03.06.2026 08:00"),
        ])
        client.post(
            "/api/inventory/import/stock",
            files={"file": ("stok.xlsx", stock, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        client.post("/api/shipment/targets", json={"reference": "REF-BULK", "target_quantity": 20})
        client.post("/api/shipment/find")

        inv_list = client.get("/api/inventory/labels").json()
        first_two_ids = [inv_list["items"][0]["id"], inv_list["items"][1]["id"]]

        # Toplu gizle (ilk 2 etiketi gizle -> 03.06.2026 kalmalı)
        res_hide = client.patch("/api/inventory/labels/bulk-hidden", json={"label_ids": first_two_ids, "hidden": True})
        assert res_hide.status_code == 200
        assert res_hide.json()["updated"] == 2

        m_after = client.get("/api/shipment/manifest").json()[0]
        assert [it["fifo_group_date"] for it in m_after["items"]] == ["03.06.2026"]

        # Toplu aktif et (ilk 2 etiketi geri aç -> 01.06.2026 geri gelmeli)
        res_unhide = client.patch("/api/inventory/labels/bulk-hidden", json={"label_ids": first_two_ids, "hidden": False})
        assert res_unhide.status_code == 200
        assert res_unhide.json()["updated"] == 2

        m_restored = client.get("/api/shipment/manifest").json()[0]
        assert [it["fifo_group_date"] for it in m_restored["items"]] == ["01.06.2026"]


class TestSixConsecutiveShipmentsExtremeStress:
    """
    5-6+ sevkiyatın art arda girildiği, düzensiz/küsuratlı etiket miktarlarının
    aynı gün içinde parçalı bölündüğü, çapraz etiket okutmalarının, gizlemelerin
    ve sıralama permütasyonlarının matematiksel değişmezlerle (invariants) sınandığı
    en ağır stres testleri.
    """

    @staticmethod
    def _assert_system_invariants(db):
        from sqlalchemy import func

        # 1. Hiçbir stok etiketi kendi miktarından fazla tahsis edilemez
        over_allocated = (
            db.query(
                ShipmentLabel.inventory_label_id,
                func.sum(ShipmentLabel.allocated_quantity).label("tot_alloc"),
                InventoryLabel.quantity,
            )
            .join(InventoryLabel, ShipmentLabel.inventory_label_id == InventoryLabel.id)
            .join(Shipment, ShipmentLabel.shipment_id == Shipment.id)
            .filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]))
            .group_by(ShipmentLabel.inventory_label_id, InventoryLabel.quantity)
            .all()
        )
        for inv_id, tot_alloc, inv_qty in over_allocated:
            assert Decimal(str(tot_alloc)) <= Decimal(str(inv_qty)) + Decimal("0.001"), (
                f"Label {inv_id} over-allocated: {tot_alloc} > {inv_qty}"
            )

        # 2. Her sevkiyatın tarih kotaları toplamı == toplam allocated_quantity olmalı
        active_shipments = (
            db.query(Shipment)
            .filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]))
            .all()
        )
        for s in active_shipments:
            sl_sum = (
                db.query(func.coalesce(func.sum(ShipmentLabel.allocated_quantity), 0))
                .filter(ShipmentLabel.shipment_id == s.id)
                .scalar()
            )
            q_sum = (
                db.query(func.coalesce(func.sum(ShipmentDateQuota.quota_quantity), 0))
                .filter(ShipmentDateQuota.shipment_id == s.id)
                .scalar()
            )
            assert abs(Decimal(str(sl_sum)) - Decimal(str(q_sum))) <= Decimal("0.001"), (
                f"Shipment {s.id} ({s.reference}) sl_sum={sl_sum} != quota_sum={q_sum}"
            )

    def test_6_consecutive_shipments_irregular_quantities_and_invariants(self, db):
        """
        10 referans, her referansta 6 farklı günde düzensiz miktarlarda 14 etiket
        (toplam 356 adet/referans).
        6 sevkiyat art arda giriliyor: talepler [55, 70, 48, 85, 62, 75] -> toplam 395 adet.
        İlk 5 sevkiyatın toplam talebi = 55+70+48+85+62 = 320 <= 356 (eksik = 0).
        6. sevkiyat ise kalan 36 adedi alır ve tam 75 - 36 = 39 adet eksik gösterir!
        """
        box_Play = [
            (0, 8, 17), (0, 11, 23), (0, 15, 30),
            (1, 9, 45), (1, 14, 12),
            (2, 8, 8),  (2, 10, 50), (2, 16, 19),
            (3, 9, 33), (3, 13, 15),
            (4, 8, 27), (4, 12, 41),
            (5, 9, 14), (5, 15, 22),
        ]
        assert sum(q for _, _, q in box_Play) == 356

        base_dt = datetime(2026, 6, 1)
        refs = [f"REF-6S-{i:02d}" for i in range(1, 11)]
        for r_idx, ref in enumerate(refs, start=1):
            for b_idx, (day_off, hour_val, qty_val) in enumerate(box_Play, start=1):
                add_inv(
                    db,
                    f"IRR-{r_idx:02d}-{b_idx:02d}",
                    ref,
                    qty_val,
                    base_dt + timedelta(days=day_off, hours=hour_val),
                )

        demands = [55, 70, 48, 85, 62, 75]
        for s_idx, req_qty in enumerate(demands, start=1):
            for ref in refs:
                add_target(db, ref, Decimal(str(req_qty)), source_name=f"{s_idx}. Sevkiyat")
            find_shipments(db)
            self._assert_system_invariants(db)

        groups = get_shipment_groups(db)
        assert len(groups) == 6

        # İlk 5 sevkiyatta 10 referansın tamamında eksik = 0 olmalı
        for pos in range(5):
            for item in groups[pos]["items"]:
                assert item["short_quantity"] == 0.0
        # 6. sevkiyatta 10 referansın tamamında eksik = 39.0 olmalı (75 - 36 = 39)
        for item in groups[5]["items"]:
            assert item["short_quantity"] == 39.0

        # Şimdi 6 sevkiyatı farklı sıralamalara (permütasyonlara) sokup her seferinde
        # matematiksel değişmezleri ve eksik miktarını doğrula!
        gids = [g["group_id"] for g in groups]
        demand_by_gid = {groups[i]["group_id"]: demands[i] for i in range(6)}

        test_orders = [
            [gids[5], gids[0], gids[1], gids[2], gids[3], gids[4]],  # 6. sevkiyat en üste!
            [gids[5], gids[4], gids[3], gids[2], gids[1], gids[0]],  # Tam ters sıra!
            [gids[2], gids[5], gids[0], gids[4], gids[1], gids[3]],  # Karma sıra 1
            [gids[3], gids[1], gids[5], gids[0], gids[4], gids[2]],  # Karma sıra 2
            gids,                                                    # Orijinal sıra
        ]

        for order in test_orders:
            reordered = reorder_shipment_groups(db, order)
            self._assert_system_invariants(db)
            assert [g["group_id"] for g in reordered] == order

            # İlk 5 sıradaki sevkiyatların toplam talebi her permütasyonda <= 356 olduğu için
            # ilk 5 sıradaki hiçbir sevkiyatta eksik çıkmamalı, sadece 6. sıradakinde exactamente 39 eksik çıkmalı!
            for pos in range(5):
                for item in reordered[pos]["items"]:
                    assert item["short_quantity"] == 0.0, (
                        f"Order {order} pos {pos} ({item['reference']}) unexpected short={item['short_quantity']}"
                    )
            for item in reordered[5]["items"]:
                assert item["short_quantity"] == 39.0

    def test_cross_label_scan_on_shared_fifo_date_across_6_shipments_never_causes_false_shortage(self, db):
        """
        Aynı FIFO gününde (01.06.2026) 6 etiket × 30 adet = 180 adet stok var.
        6 sevkiyat art arda açılıyor (her biri 30 adet istiyor).
        Operatör 1. sevkiyata 6. etiketi (SHARED-6), 2. sevkiyata 5. etiketi (SHARED-5)...
        yani tahmin edilenin tam tersi etiketleri okutuyor!
        Hiçbir adımda hiçbir sevkiyatta sahte 'Eksik' (short_quantity > 0) oluşmamalı!
        """
        for i in range(1, 7):
            add_inv(db, f"SHARED-{i}", "REF-SHARED", 30, datetime(2026, 6, 1, 8, i))

        for i in range(1, 7):
            add_target(db, "REF-SHARED", Decimal("30"), source_name=f"S{i}")
            find_shipments(db)

        groups = get_shipment_groups(db)
        assert len(groups) == 6

        # Ters sırayla etiketleri okut: S1 -> SHARED-6, S2 -> SHARED-5, ..., S6 -> SHARED-1
        for idx in range(6):
            target_gid = groups[idx]["group_id"]
            label_to_scan = f"SHARED-{6 - idx}"
            res = process_global_scan(db, label_to_scan, target_group_id=target_gid)
            assert res.success is True, f"Failed scanning {label_to_scan} into group {target_gid}: {res}"
            self._assert_system_invariants(db)

            # Okutma sonrası tüm 6 sevkiyatı kontrol et: hiçbirinde short_quantity > 0 olmamalı!
            current_groups = get_shipment_groups(db)
            for g in current_groups:
                it = g["items"][0]
                assert it["short_quantity"] == 0.0, (
                    f"After scanning {label_to_scan}, group {g['name']} falsely showed short={it['short_quantity']}"
                )
                assert it["stock_note"] is None

    def test_6_shipments_full_lifecycle_scans_undo_hide_delete_and_reorder(self, client):
        """
        Uçtan uca 6 sevkiyatlı kaos testi:
        - 6 sevkiyat oluşturulur
        - Bazılarında okutma yapılır
        - Stok listesinden bir etiket gizlenir (hidden=True) -> en alttaki sevkiyatta eksik oluştuğu doğrulanır
        - Etiket tekrar aktif edilir (hidden=False) -> eksiğin kaybolduğu doğrulanır
        - Bir okutma geri alınır (undo)
        - Sıralama değiştirilir ve tekrar hesaplanır
        """
        stock = make_stock_excel([
            (f"chaos-{i}", "REF-CHAOS", 25, f"0{i}.06.2026 08:00")
            for i in range(1, 7)
        ])
        client.post(
            "/api/inventory/import/stock",
            files={"file": ("stok.xlsx", stock, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

        for i in range(1, 7):
            client.post("/api/shipment/targets", json={"reference": "REF-CHAOS", "target_quantity": 25})
            client.post("/api/shipment/find")

        groups = client.get("/api/shipment/groups").json()
        assert len(groups) == 6
        assert all(g["items"][0]["short_quantity"] == 0.0 for g in groups)

        # 2. sevkiyatta chaos-2 etiketini okut
        g2_id = groups[1]["group_id"]
        s2_id = groups[1]["items"][0]["shipment_id"]
        scan_res = client.post("/api/shipment/scan", json={"label": "chaos-2", "group_id": g2_id}).json()
        assert scan_res["success"] is True

        # Stok listesinden okutulmamış chaos-6 etiketini gizle
        lbl_res = client.get("/api/inventory/labels?q=chaos-6").json()
        c6_id = lbl_res["items"][0]["id"]
        client.patch(f"/api/inventory/labels/{c6_id}/hidden", json={"hidden": True})

        # Artık toplam aktif stok 125'e düştüğü için 6. sevkiyat 25 eksik göstermeli!
        groups_hidden = client.get("/api/shipment/groups").json()
        assert groups_hidden[5]["items"][0]["short_quantity"] == 25.0
        assert groups_hidden[5]["items"][0]["stock_note"] == "Eksik"

        # 6. sevkiyatı 1. sıraya taşı! Artık 6. sevkiyat (yeni 1. sıra) tam stok almalı, en sona düşen 5. sevkiyat Eksik olmalı!
        gids = [g["group_id"] for g in groups_hidden]
        new_order = [gids[5], gids[0], gids[1], gids[2], gids[3], gids[4]]
        reordered = client.put("/api/shipment/groups/order", json={"group_ids": new_order}).json()
        assert reordered[0]["items"][0]["short_quantity"] == 0.0
        assert reordered[5]["items"][0]["short_quantity"] == 25.0

        # Gizlenen chaos-6 etiketini tekrar aktif et -> tüm 6 sevkiyatta eksik 0 olmalı!
        client.patch(f"/api/inventory/labels/{c6_id}/hidden", json={"hidden": False})
        groups_restored = client.get("/api/shipment/groups").json()
        assert all(g["items"][0]["short_quantity"] == 0.0 for g in groups_restored)

        # S2'deki okutmayı geri al (undo)
        undo_res = client.delete(f"/api/shipment/{s2_id}/scans/chaos-2")
        assert undo_res.status_code == 200
        groups_final = client.get("/api/shipment/groups").json()
        assert all(g["items"][0]["short_quantity"] == 0.0 for g in groups_final)
