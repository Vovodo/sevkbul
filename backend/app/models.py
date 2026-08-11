import enum
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Numeric, Index, Boolean, Enum as SAEnum
)
from sqlalchemy.orm import relationship

from app.database import Base


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


class InventoryLabel(Base):
    __tablename__ = "inventory_labels"

    id = Column(Integer, primary_key=True, index=True)
    label = Column(String(100), unique=True, nullable=False, index=True)
    reference = Column(String(200), nullable=False, index=True)
    quantity = Column(Numeric(12, 2), nullable=False)
    fifo_date = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    shipment_labels = relationship("ShipmentLabel", back_populates="inventory_label")


class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(200), nullable=False, index=True)
    requested_quantity = Column(Numeric(12, 2), nullable=False)
    status = Column(SAEnum(ShipmentStatus), default=ShipmentStatus.ACTIVE, index=True)
    hourly_fifo = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    shipment_labels = relationship("ShipmentLabel", back_populates="shipment", cascade="all, delete-orphan")
    scan_logs = relationship("ScanLog", back_populates="shipment", cascade="all, delete-orphan")


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


class ScanLog(Base):
    __tablename__ = "scan_logs"

    id = Column(Integer, primary_key=True, index=True)
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


class ShipmentTarget(Base):
    """Sevkiyat hedefi — Excel veya manuel giriş, FIFO hesabından önce."""
    __tablename__ = "shipment_targets"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(200), nullable=False, index=True)
    target_quantity = Column(Numeric(12, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
