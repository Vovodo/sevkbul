import enum
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Numeric, Index, Boolean,
    LargeBinary, UniqueConstraint, Enum as SAEnum,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.session_context import get_current_session_id


class SessionScopedMixin:
    """Nesne oluşturulurken aktif session_id değerini otomatik atar."""

    def __init__(self, **kwargs):
        if "session_id" not in kwargs or kwargs["session_id"] is None:
            kwargs["session_id"] = get_current_session_id()
        super().__init__(**kwargs)


class WorkSession(Base):
    """Çoklu Oturum / Çalışma Alanı (Personel 1 - X Projesi, Personel 2 - Y Projesi vb.)."""
    __tablename__ = "work_sessions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    staff_name = Column(String(150), nullable=True)
    description = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ShipmentStatus(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ShipmentLabelStatus(str, enum.Enum):
    PENDING = "pending"
    SCANNED = "scanned"
    PARTIAL = "partial"


class ScanResult(str, enum.Enum):
    SHIPMENT_PRODUCT = "SEVKİYAT ÜRÜNÜ"
    OUTSIDE_SHIPMENT = "SEVKİYAT DIŞI"
    NOT_FOUND = "ETİKET BULUNAMADI"
    ALREADY_SCANNED = "ZATEN OKUTULDU"
    QUANTITY_EXCEEDED = "MİKTAR AŞILDI"
    BLOCKED_LABEL = "BLOKAJLI ETİKET"
    NOT_BLOCKED_LABEL = "BLOKAJLI DEĞİL"


class InventoryLabel(SessionScopedMixin, Base):
    __tablename__ = "inventory_labels"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, default=get_current_session_id, nullable=False, index=True)
    label = Column(String(100), nullable=False, index=True)
    reference = Column(String(200), nullable=False, index=True)
    quantity = Column(Numeric(12, 2), nullable=False)
    fifo_date = Column(DateTime, nullable=False, index=True)
    blocked = Column(Boolean, default=False, nullable=False, index=True)
    hidden = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    shipment_labels = relationship("ShipmentLabel", back_populates="inventory_label")

    __table_args__ = (
        UniqueConstraint("session_id", "label", name="uq_session_inventory_label"),
        Index("ix_inv_session_ref_fifo", "session_id", "reference", "fifo_date"),
    )


class Shipment(SessionScopedMixin, Base):
    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, default=get_current_session_id, nullable=False, index=True)
    group_id = Column(Integer, nullable=True, index=True)
    group_name = Column(String(200), nullable=True)
    sort_order = Column(Integer, nullable=True, index=True)
    reference = Column(String(200), nullable=False, index=True)
    requested_quantity = Column(Numeric(12, 2), nullable=False)
    status = Column(SAEnum(ShipmentStatus), default=ShipmentStatus.ACTIVE, index=True)
    hourly_fifo = Column(Boolean, default=False, nullable=False)
    name = Column(String(200), nullable=True)
    stock_note = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, default=datetime.utcnow, nullable=True)

    shipment_labels = relationship("ShipmentLabel", back_populates="shipment", cascade="all, delete-orphan")
    date_quotas = relationship("ShipmentDateQuota", back_populates="shipment", cascade="all, delete-orphan")
    scan_logs = relationship("ScanLog", back_populates="shipment", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_shipments_session_status", "session_id", "status"),
    )


class ShipmentLabel(Base):
    __tablename__ = "shipment_labels"

    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"), nullable=False, index=True)
    inventory_label_id = Column(Integer, ForeignKey("inventory_labels.id"), nullable=False)
    allocated_quantity = Column(Numeric(12, 2), nullable=False)
    scanned_quantity = Column(Numeric(12, 2), default=0)
    status = Column(SAEnum(ShipmentLabelStatus), default=ShipmentLabelStatus.PENDING)

    shipment = relationship("Shipment", back_populates="shipment_labels")
    inventory_label = relationship("InventoryLabel", back_populates="shipment_labels")

    __table_args__ = (
        Index("ix_shipment_labels_shipment_inventory", "shipment_id", "inventory_label_id"),
    )


class ScanLog(SessionScopedMixin, Base):
    __tablename__ = "scan_logs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, default=get_current_session_id, nullable=False, index=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"), nullable=True, index=True)
    inventory_label_id = Column(Integer, ForeignKey("inventory_labels.id"), nullable=True)
    scanned_value = Column(String(100), nullable=False)
    result = Column(SAEnum(ScanResult), nullable=False)
    scanned_at = Column(DateTime, default=datetime.utcnow, index=True)

    shipment = relationship("Shipment", back_populates="scan_logs")
    inventory_label = relationship("InventoryLabel")

    __table_args__ = (
        Index("ix_scan_logs_shipment_scanned_at", "shipment_id", "scanned_at"),
    )


class ShipmentDateQuota(Base):
    """Sevkiyatın bir FIFO tarihinde kabul edeceği miktar.

    Barkod bu tarihe kilitlenmez. Kota dolana kadar aynı tarihteki
    okutulmamış herhangi bir etiket bu sevkiyata yazılabilir.
    """

    __tablename__ = "shipment_date_quotas"

    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"), nullable=False, index=True)
    fifo_group = Column(DateTime, nullable=False)
    quota_quantity = Column(Numeric(12, 2), nullable=False)

    shipment = relationship("Shipment", back_populates="date_quotas")

    __table_args__ = (
        UniqueConstraint("shipment_id", "fifo_group", name="uq_shipment_fifo_group"),
    )


class ShipmentTarget(SessionScopedMixin, Base):
    """Sevkiyat hedefi — Excel veya manuel giriş, FIFO hesabından önce."""
    __tablename__ = "shipment_targets"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, default=get_current_session_id, nullable=False, index=True)
    reference = Column(String(200), nullable=False, index=True)
    target_quantity = Column(Numeric(12, 2), nullable=False)
    source_name = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ExcelHeaderSettings(SessionScopedMixin, Base):
    """Excel sütun üst başlığı eşleştirme ayarları (her oturum için bağımsız)."""
    __tablename__ = "excel_header_settings"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, default=get_current_session_id, nullable=False, index=True)
    label_header = Column(String(200), default="ETİKET", nullable=False)
    reference_header = Column(String(200), default="REFERANS", nullable=False)
    quantity_header = Column(String(200), default="MİKTAR", nullable=False)
    fifo_date_header = Column(String(200), default="X98FIFO_TARIH", nullable=False)
    blocked_header = Column(String(200), default="BLOKAJ", nullable=False)
    shipment_reference_header = Column(String(200), default="REFERANS", nullable=False)
    shipment_quantity_header = Column(String(200), default="MİKTAR", nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StoredExcelFile(Base):
    """Mini S3 — Yüklenen Excel dosyalarının konum, üstveri ve binary saklama tablosu.
    Her oturum ve slot ('s1_stock', 's2_stock' vb.) için yalnızca en son yüklenen dosya tutulur;
    yeni Excel yüklendiğinde eski dosya hem diskten hem veritabanından otomatik silinir.
    """
    __tablename__ = "stored_excel_files"

    id = Column(Integer, primary_key=True, index=True)
    slot = Column(String(50), unique=True, nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    storage_key = Column(String(500), nullable=False)
    local_path = Column(String(500), nullable=False)
    content_type = Column(String(150), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256_hash = Column(String(64), nullable=False)
    row_count = Column(Integer, default=0, nullable=False)
    file_data = Column(LargeBinary, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
