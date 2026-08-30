"""
Çoklu Sevkiyat + FIFO Devamlılığı Entegrasyon Testleri

Kullanıcı senaryosu (hourly_fifo=True — saat bazlı gruplama):
  Stok: 6 etiket × 30 adet = 180 adet (aynı referans)
  Sevkiyat 1: 60 adet → 700022382 (10.06 13:02), 700022545 (13.06 08:24)
  Sevkiyat 2: 60 adet → 700024521 (23.07 20:39), 700024537 (23.07 20:59)
  Sevkiyat 3: 60 adet → 700024550 (23.07 22:22), 700024778 (23.07 22:22)
  Sevkiyat 4: 60 adet → YETERSİZ STOK hatası

Not:
  23.07 tarihinde 4 etiket var, ama saat FARKLI: 20:39, 20:59, 22:22, 22:22.
  - hourly_fifo=True → 4 ayrı grup → S2 ve S3'e bölünebilir ✅
  - hourly_fifo=False (gün bazlı) → tek grup → S2'de 4 etiket birlikte (120 adet) ✅

Her iki mod da doğru FIFO davranışı sergilemelidir.
"""
import pytest
from decimal import Decimal
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import InventoryLabel, ShipmentLabel, ShipmentTarget, Shipment, ShipmentStatus
from app.services.shipment_service import create_shipment_from_reference, _get_previously_allocated
from app.services.target_service import add_target, find_shipments
from app.services.lookup_cache import lookup_cache


@pytest.fixture(autouse=True)
def clear_cache():
    """Her testten önce ve sonra lookup cache'i temizle."""
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
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def make_inventory(db, label: str, reference: str, qty: float, fifo_dt: datetime) -> InventoryLabel:
    inv = InventoryLabel(
        label=label,
        reference=reference,
        quantity=Decimal(str(qty)),
        fifo_date=fifo_dt,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


def setup_six_labels(db) -> list[InventoryLabel]:
    """
    Kullanıcının verdiği örnek stok:
    700022382 → 30  (10.06.2026 13:02)
    700022545 → 30  (13.06.2026 08:24)
    700024521 → 30  (23.07.2026 20:39)
    700024537 → 30  (23.07.2026 20:59)
    700024550 → 30  (23.07.2026 22:22)
    700024778 → 30  (23.07.2026 22:22)
    """
    ref = "6681378-HZN-1"
    labels = [
        make_inventory(db, "700022382", ref, 30.0, datetime(2026, 6, 10, 13, 2)),
        make_inventory(db, "700022545", ref, 30.0, datetime(2026, 6, 13, 8, 24)),
        make_inventory(db, "700024521", ref, 30.0, datetime(2026, 7, 23, 20, 39)),
        make_inventory(db, "700024537", ref, 30.0, datetime(2026, 7, 23, 20, 59)),
        make_inventory(db, "700024550", ref, 30.0, datetime(2026, 7, 23, 22, 22)),
        make_inventory(db, "700024778", ref, 30.0, datetime(2026, 7, 23, 22, 22)),
    ]
    lookup_cache.load_all_active(db)
    return labels


def _get_allocated_labels(db, shipment_id: int) -> set:
    sls = db.query(ShipmentLabel).filter(ShipmentLabel.shipment_id == shipment_id).all()
    labels = set()
    for sl in sls:
        inv = db.query(InventoryLabel).filter(InventoryLabel.id == sl.inventory_label_id).first()
        if inv:
            labels.add(inv.label)
    return labels


def _get_labels_with_qty(db, shipment_id: int) -> dict:
    sls = db.query(ShipmentLabel).filter(ShipmentLabel.shipment_id == shipment_id).all()
    result = {}
    for sl in sls:
        inv = db.query(InventoryLabel).filter(InventoryLabel.id == sl.inventory_label_id).first()
        if inv:
            result[inv.label] = sl.allocated_quantity
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Ana senaryo: Saat bazlı FIFO (hourly_fifo=True)
# Kullanıcının tam beklediği 3 sevkiyat senaryosu
# ─────────────────────────────────────────────────────────────────────────────
class TestHourlyFifoMultiShipment:
    """Saat bazlı FIFO (hourly_fifo=True) — Kullanıcı senaryosu."""

    def test_shipment1_gets_first_two_labels(self, db):
        """S1 (60): 700022382 (10.06 13:02) + 700022545 (13.06 08:24)"""
        setup_six_labels(db)
        ref = "6681378-HZN-1"
        r1 = create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=True)

        labels = _get_allocated_labels(db, r1.shipment_id)
        assert "700022382" in labels
        assert "700022545" in labels
        assert len(labels) == 2
        assert r1.pool_quantity == Decimal("60")
        assert r1.insufficient_stock is False

    def test_shipment2_skips_shipment1_uses_next_hour_group(self, db):
        """S2 (60): 700024521 (20:39) + 700024537 (20:59) — S1'in etiketleri kullanılmamalı."""
        setup_six_labels(db)
        ref = "6681378-HZN-1"
        create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=True)
        r2 = create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=True)

        labels2 = _get_allocated_labels(db, r2.shipment_id)
        assert "700022382" not in labels2, "S1'e tahsisli etiket S2'de olmamalı"
        assert "700022545" not in labels2, "S1'e tahsisli etiket S2'de olmamalı"
        assert "700024521" in labels2
        assert "700024537" in labels2
        assert r2.pool_quantity == Decimal("60")

    def test_shipment3_gets_last_hour_group(self, db):
        """S3 (60): 700024550 (22:22) + 700024778 (22:22)"""
        setup_six_labels(db)
        ref = "6681378-HZN-1"
        create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=True)
        create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=True)
        r3 = create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=True)

        labels3 = _get_allocated_labels(db, r3.shipment_id)
        assert "700024550" in labels3
        assert "700024778" in labels3
        assert r3.pool_quantity == Decimal("60")

    def test_shipment4_has_no_available_stock(self, db):
        """S4 (60): Tüm 180 adet tükenmiş → ValueError"""
        setup_six_labels(db)
        ref = "6681378-HZN-1"
        create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=True)
        create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=True)
        create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=True)

        with pytest.raises(ValueError, match="kullanılabilir stok kalmadı"):
            create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=True)

    def test_fifo_order_strictly_preserved(self, db):
        """Sevkiyatlar arasında FIFO sıralaması bozulmamalı: S1 < S2 < S3."""
        setup_six_labels(db)
        ref = "6681378-HZN-1"
        r1 = create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=True)
        r2 = create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=True)
        r3 = create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=True)

        def get_dates(sid):
            sls = db.query(ShipmentLabel).filter(ShipmentLabel.shipment_id == sid).all()
            return [
                db.query(InventoryLabel).filter(InventoryLabel.id == sl.inventory_label_id).first().fifo_date
                for sl in sls
            ]

        dates1 = get_dates(r1.shipment_id)
        dates2 = get_dates(r2.shipment_id)
        dates3 = get_dates(r3.shipment_id)

        assert max(dates1) <= min(dates2), "S1 etiketleri S2'dekinden eski olmalı"
        assert max(dates2) <= min(dates3), "S2 etiketleri S3'tekinden eski/eşit olmalı"


# ─────────────────────────────────────────────────────────────────────────────
# Gün bazlı FIFO (hourly_fifo=False) — Mevcut davranış korunmalı
# ─────────────────────────────────────────────────────────────────────────────
class TestDailyFifoMultiShipment:
    """Gün bazlı FIFO (hourly_fifo=False) — 23.07'deki 4 etiket tek grup."""

    def test_shipment1_gets_june_labels(self, db):
        """S1 (60): Haziran etiketleri (10.06 + 13.06)"""
        setup_six_labels(db)
        ref = "6681378-HZN-1"
        r1 = create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=False)

        labels = _get_allocated_labels(db, r1.shipment_id)
        assert "700022382" in labels
        assert "700022545" in labels
        assert r1.pool_quantity == Decimal("60")

    def test_shipment2_gets_july_group_all_four(self, db):
        """S2 (60): 23.07 grubu — tüm grup havuza girer, kota 60."""
        setup_six_labels(db)
        ref = "6681378-HZN-1"
        create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=False)
        r2 = create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=False)

        labels2 = _get_allocated_labels(db, r2.shipment_id)
        # 23.07 grubu tüm havuza girer (4 etiket) ama kota 60
        july_labels = {"700024521", "700024537", "700024550", "700024778"}
        # S2'de en az 23.07 etiketleri olmalı, Haziran etiketleri olmamalı
        assert "700022382" not in labels2
        assert "700022545" not in labels2
        assert len(labels2.intersection(july_labels)) > 0

    def test_no_june_labels_in_shipment2(self, db):
        """S2'de Haziran etiketleri kesinlikle olmamalı."""
        setup_six_labels(db)
        ref = "6681378-HZN-1"
        create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=False)
        r2 = create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=False)

        labels2 = _get_allocated_labels(db, r2.shipment_id)
        assert "700022382" not in labels2
        assert "700022545" not in labels2


# ─────────────────────────────────────────────────────────────────────────────
# _get_previously_allocated() doğruluk testleri
# ─────────────────────────────────────────────────────────────────────────────
class TestPreviouslyAllocated:
    """_get_previously_allocated() doğru veri döndürmeli."""

    def test_empty_before_any_shipment(self, db):
        """Hiç sevkiyat yokken boş sözlük döner."""
        setup_six_labels(db)
        result = _get_previously_allocated(db, "6681378-HZN-1")
        assert result == {}

    def test_correct_allocation_after_first_shipment(self, db):
        """S1 (60) sonrası 700022382 ve 700022545 tahsisli görünmeli."""
        setup_six_labels(db)
        ref = "6681378-HZN-1"
        create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=True)

        allocated = _get_previously_allocated(db, ref)

        inv1 = db.query(InventoryLabel).filter(InventoryLabel.label == "700022382").first()
        inv2 = db.query(InventoryLabel).filter(InventoryLabel.label == "700022545").first()
        inv3 = db.query(InventoryLabel).filter(InventoryLabel.label == "700024521").first()

        assert allocated.get(inv1.id) == Decimal("30")
        assert allocated.get(inv2.id) == Decimal("30")
        assert inv3.id not in allocated, "Henüz tahsis edilmemiş etiket sözlükte olmamalı"

    def test_cumulative_allocation_after_two_shipments(self, db):
        """S1 + S2 sonrası 4 etiket tahsisli görünmeli."""
        setup_six_labels(db)
        ref = "6681378-HZN-1"
        create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=True)
        create_shipment_from_reference(db, ref, Decimal("60"), hourly_fifo=True)

        allocated = _get_previously_allocated(db, ref)
        # 4 etiket tahsisli olmalı
        assert len(allocated) == 4

        inv5 = db.query(InventoryLabel).filter(InventoryLabel.label == "700024550").first()
        inv6 = db.query(InventoryLabel).filter(InventoryLabel.label == "700024778").first()
        assert inv5.id not in allocated, "S3 etiketleri henüz tahsisli olmamalı"
        assert inv6.id not in allocated

    def test_different_reference_not_affected(self, db):
        """Başka referansın tahsisleri bu referansı etkilemez."""
        setup_six_labels(db)
        # Farklı referans ekle
        make_inventory(db, "OTHER001", "DIGER-REF", 30.0, datetime(2026, 6, 1, 10, 0))
        lookup_cache.load_all_active(db)

        create_shipment_from_reference(db, "DIGER-REF", Decimal("30"))

        allocated = _get_previously_allocated(db, "6681378-HZN-1")
        # Ana referans etkilenmemiş olmalı
        assert allocated == {}


# ─────────────────────────────────────────────────────────────────────────────
# Tek sevkiyat — geriye dönük uyumluluk
# ─────────────────────────────────────────────────────────────────────────────
class TestSingleShipmentBackwardCompat:
    """Tek sevkiyat senaryoları eskisi gibi çalışmalı."""

    def test_single_60_from_six_labels_hourly(self, db):
        """Tek S (60 adet, hourly): İlk 2 etiket."""
        setup_six_labels(db)
        result = create_shipment_from_reference(db, "6681378-HZN-1", Decimal("60"), hourly_fifo=True)
        assert result.pool_quantity == Decimal("60")
        assert result.insufficient_stock is False

        labels = _get_allocated_labels(db, result.shipment_id)
        assert "700022382" in labels
        assert "700022545" in labels

    def test_single_60_from_six_labels_daily(self, db):
        """Tek S (60 adet, daily): İlk 2 etiket."""
        setup_six_labels(db)
        result = create_shipment_from_reference(db, "6681378-HZN-1", Decimal("60"), hourly_fifo=False)
        assert result.pool_quantity == Decimal("60")
        assert result.insufficient_stock is False

        labels = _get_allocated_labels(db, result.shipment_id)
        assert "700022382" in labels
        assert "700022545" in labels

    def test_single_shipment_full_stock(self, db):
        """Tek S (180 adet): Tüm stok."""
        setup_six_labels(db)
        result = create_shipment_from_reference(db, "6681378-HZN-1", Decimal("180"), hourly_fifo=True)
        assert result.pool_quantity == Decimal("180")
        assert result.insufficient_stock is False
        assert result.label_count == 6

    def test_insufficient_stock_single_shipment(self, db):
        """Tek S (200 adet): Stok yetersiz → insufficient_stock=True."""
        setup_six_labels(db)
        result = create_shipment_from_reference(db, "6681378-HZN-1", Decimal("200"), hourly_fifo=True)
        assert result.insufficient_stock is True
        assert result.remaining_unfulfilled == Decimal("20")


# ─────────────────────────────────────────────────────────────────────────────
# Farklı referanslar birbirini etkilememeli
# ─────────────────────────────────────────────────────────────────────────────
class TestDifferentReferences:
    """Ref-A ve Ref-B sevkiyatları birbirinin FIFO'sunu etkilemez."""

    def test_ref_a_and_ref_b_independent(self, db):
        ref_a = "REF-A"
        ref_b = "REF-B"

        for i in range(4):
            make_inventory(db, f"A{i+1}", ref_a, 30.0, datetime(2026, 7, i+1, 10, 0))
        for i in range(4):
            make_inventory(db, f"B{i+1}", ref_b, 30.0, datetime(2026, 7, i+1, 10, 0))

        lookup_cache.load_all_active(db)

        rA1 = create_shipment_from_reference(db, ref_a, Decimal("60"))
        rB1 = create_shipment_from_reference(db, ref_b, Decimal("60"))

        labels_a = _get_allocated_labels(db, rA1.shipment_id)
        labels_b = _get_allocated_labels(db, rB1.shipment_id)

        # A ve B etiketleri kesinlikle karışmamalı
        assert not labels_a.intersection(labels_b)
        assert all(lbl.startswith("A") for lbl in labels_a)
        assert all(lbl.startswith("B") for lbl in labels_b)

    def test_multi_shipment_ref_a_doesnt_affect_ref_b(self, db):
        """Ref-A'nın S2'si Ref-B'nin FIFO'sunu etkilemez."""
        ref_a = "REF-A"
        ref_b = "REF-B"

        for i in range(4):
            make_inventory(db, f"A{i+1}", ref_a, 30.0, datetime(2026, 7, i+1, 10, 0))
        for i in range(4):
            make_inventory(db, f"B{i+1}", ref_b, 30.0, datetime(2026, 7, i+1, 10, 0))

        lookup_cache.load_all_active(db)

        # Ref-A: 2 sevkiyat
        create_shipment_from_reference(db, ref_a, Decimal("60"))
        create_shipment_from_reference(db, ref_a, Decimal("60"))

        # Ref-B: 1 sevkiyat — etkilenmemiş olmalı
        rB1 = create_shipment_from_reference(db, ref_b, Decimal("60"))
        labels_b = _get_allocated_labels(db, rB1.shipment_id)

        assert "B1" in labels_b
        assert "B2" in labels_b
        assert all(lbl.startswith("B") for lbl in labels_b)


# ─────────────────────────────────────────────────────────────────────────────
# find_shipments() — Çoklu çağrı devamlılığı
# ─────────────────────────────────────────────────────────────────────────────
class TestFindShipmentsContinuity:
    """find_shipments() art arda çağrılınca FIFO devam eder, sıfırlamaz."""

    def test_second_find_continues_from_first(self, db):
        """2. SEVKİYATI BUL çağrısı, 1. sevkiyatın ettiği etiketleri tekrar almamalı."""
        setup_six_labels(db)
        ref = "6681378-HZN-1"

        # 1. find_shipments çağrısı
        add_target(db, ref, Decimal("60"))
        result1 = find_shipments(db, hourly_fifo=True)
        assert len(result1["shipments"]) == 1
        s1_id = result1["shipments"][0]["shipment_id"]
        labels1 = _get_allocated_labels(db, s1_id)

        # 2. find_shipments çağrısı (aynı referans)
        add_target(db, ref, Decimal("60"))
        result2 = find_shipments(db, hourly_fifo=True)
        assert len(result2["shipments"]) == 1
        s2_id = result2["shipments"][0]["shipment_id"]
        labels2 = _get_allocated_labels(db, s2_id)

        # S1 ve S2 etiketleri örtüşmemeli
        assert not labels1.intersection(labels2), \
            f"S1 ve S2 aynı etiketlere sahip olmamalı! Ortak: {labels1 & labels2}"

        # S2 S1'dekilerden daha güncel FIFO tarihlerine sahip olmalı
        def get_fifo_dates(labels_set):
            dates = []
            for lbl in labels_set:
                inv = db.query(InventoryLabel).filter(InventoryLabel.label == lbl).first()
                if inv:
                    dates.append(inv.fifo_date)
            return dates

        dates1 = get_fifo_dates(labels1)
        dates2 = get_fifo_dates(labels2)
        assert max(dates1) <= min(dates2), "S2 etiketleri S1'dekinden daha yeni olmalı"
