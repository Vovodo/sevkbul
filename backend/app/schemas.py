from pydantic import BaseModel
from decimal import Decimal
from datetime import datetime


class RowErrorSchema(BaseModel):
    row: int
    reason: str
    error_type: str = "general"


class ImportPreviewRowSchema(BaseModel):
    label: str
    reference: str
    quantity: float
    fifo_date: str


class ImportResultSchema(BaseModel):
    total_rows: int
    successful: int
    error_count: int
    duplicate_count: int
    invalid_label_count: int
    invalid_reference_count: int
    invalid_quantity_count: int
    invalid_fifo_date_count: int
    errors: list[RowErrorSchema]
    duplicate_labels: list[str]
    missing_columns: list[str]
    preview_rows: list[ImportPreviewRowSchema]


class ShipmentCreateRequest(BaseModel):
    reference: str
    requested_quantity: Decimal


class ShipmentCreateResponse(BaseModel):
    shipment_id: int
    reference: str
    requested_quantity: float
    pool_quantity: float
    label_count: int
    fifo_group_count: int
    insufficient_stock: bool
    remaining_unfulfilled: float


class ShipmentProgressSchema(BaseModel):
    shipment_id: int
    reference: str
    requested_quantity: float
    pool_quantity: float
    scanned_quantity: float
    remaining_quantity: float
    progress_percent: float
    status: str
    is_complete: bool


class ScanRequest(BaseModel):
    label: str


class ScanResponseSchema(BaseModel):
    result: str
    label: str
    reference: str | None = None
    quantity: float | None = None
    scanned_quantity: float | None = None
    remaining_quantity: float | None = None
    progress_percent: float = 0
    is_complete: bool = False
    shipment_id: int | None = None
    fifo_date: str | None = None
    success: bool = False
    already_scanned: bool = False


class ShipmentTargetSchema(BaseModel):
    id: int
    reference: str
    target_quantity: float


class ShipmentTargetCreateSchema(BaseModel):
    reference: str
    target_quantity: Decimal


class ShipmentFindResultSchema(BaseModel):
    shipments: list[ShipmentProgressSchema]
    errors: list[dict]


class ShipmentTargetImportResultSchema(BaseModel):
    total_rows: int
    successful: int
    error_count: int
    errors: list[RowErrorSchema]
    missing_columns: list[str]
    targets: list[ShipmentTargetSchema]


class ScanLogSchema(BaseModel):
    id: int
    scanned_value: str
    reference: str | None
    quantity: float | None
    result: str
    scanned_at: datetime

    class Config:
        from_attributes = True


class DashboardSchema(BaseModel):
    active_shipments: int
    today_shipments: int
    completed_shipments: int
    in_progress_shipments: int
    total_scans: int
    error_scans: int


class InventoryStatsSchema(BaseModel):
    total_labels: int
    total_references: int


class ShipmentLabelSchema(BaseModel):
    label: str
    reference: str
    allocated_quantity: float
    total_quantity: float
    fifo_date: str
    fifo_group_date: str
    status: str


class ScannedLabelSchema(BaseModel):
    label: str
    quantity: float
    fifo_date: str
    scanned_at: str | None = None


class ShipmentImportRowSchema(BaseModel):
    reference: str
    quantity: float
    shipment_id: int | None
    label_count: int
    pool_quantity: float
    insufficient_stock: bool


class ShipmentImportResultSchema(BaseModel):
    total_rows: int
    successful: int
    error_count: int
    errors: list[RowErrorSchema]
    missing_columns: list[str]
    shipments: list[ShipmentImportRowSchema]
