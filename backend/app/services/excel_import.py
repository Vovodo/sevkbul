from dataclasses import dataclass, field
from decimal import Decimal
from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.models import InventoryLabel
from app.utils.excel_parser import (
    find_column_mapping,
    get_excel_header_settings_dict,
    parse_label,
    parse_quantity,
    parse_reference,
    parse_fifo_datetime,
    parse_blocked,
    format_fifo_datetime,
    REQUIRED_COLUMNS,
)


@dataclass
class RowError:
    row: int
    reason: str
    error_type: str = "general"


@dataclass
class ImportPreviewRow:
    label: str
    reference: str
    quantity: float
    fifo_date: str


@dataclass
class ImportResult:
    total_rows: int = 0
    successful: int = 0
    errors: list[RowError] = field(default_factory=list)
    duplicate_labels: list[str] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)
    invalid_label_count: int = 0
    invalid_reference_count: int = 0
    invalid_quantity_count: int = 0
    invalid_fifo_date_count: int = 0
    preview_rows: list[ImportPreviewRow] = field(default_factory=list)


def import_excel(db: Session, file_content: bytes, replace_existing: bool = True) -> ImportResult:
    result = ImportResult()

    try:
        wb = load_workbook(BytesIO(file_content), read_only=True, data_only=True)
    except Exception:
        result.errors.append(RowError(row=0, reason="Excel dosyası açılamadı"))
        return result

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        result.errors.append(RowError(row=0, reason="Excel dosyası boş"))
        return result

    headers = rows[0]
    custom_headers = get_excel_header_settings_dict(db)
    header_row_idx = 0
    mapping = find_column_mapping(list(headers), custom_headers=custom_headers)

    required_by_field = [
        ("label", custom_headers.get("label_header") or "ETİKET"),
        ("reference", custom_headers.get("reference_header") or "REFERANS"),
        ("quantity", custom_headers.get("quantity_header") or "MİKTAR"),
        ("fifo_date", custom_headers.get("fifo_date_header") or "X98FIFO_TARIH"),
    ]
    missing = [
        hdr_label
        for field_name, hdr_label in required_by_field
        if field_name not in mapping
    ]
    # Eğer 1. satır boşsa veya rapor başlığıysa, ilk 10 satır içinde başlık satırını ara
    if missing and len(rows) > 1:
        for cand_idx in range(1, min(len(rows), 10)):
            cand_map = find_column_mapping(list(rows[cand_idx]), custom_headers=custom_headers)
            if all(fn in cand_map for fn, _ in required_by_field):
                mapping = cand_map
                header_row_idx = cand_idx
                missing = []
                break

    if missing:
        result.missing_columns = missing
        return result

    from app.models import Shipment, ShipmentLabel, ShipmentDateQuota, ScanLog, ShipmentStatus, ShipmentLabelStatus
    if replace_existing:
        cancelled_ids = [
            r[0]
            for r in db.query(Shipment.id).filter(Shipment.status == ShipmentStatus.CANCELLED).all()
        ]
        if cancelled_ids:
            db.query(ShipmentDateQuota).filter(ShipmentDateQuota.shipment_id.in_(cancelled_ids)).delete(synchronize_session=False)
            db.query(ShipmentLabel).filter(ShipmentLabel.shipment_id.in_(cancelled_ids)).delete(synchronize_session=False)
            db.query(ScanLog).filter(ScanLog.shipment_id.in_(cancelled_ids)).delete(synchronize_session=False)
            db.query(Shipment).filter(Shipment.id.in_(cancelled_ids)).delete(synchronize_session=False)
            db.flush()

    existing_rows = db.query(InventoryLabel).all()
    existing_by_label: dict[str, InventoryLabel] = {r.label: r for r in existing_rows}

    seen_labels: set[str] = set()
    batch: list[InventoryLabel] = []
    BATCH_SIZE = 1000
    PREVIEW_LIMIT = 5

    for row_idx, row in enumerate(rows[header_row_idx + 1:], start=header_row_idx + 2):
        result.total_rows += 1

        label_val = row[mapping["label"]] if mapping["label"] < len(row) else None
        ref_val = row[mapping["reference"]] if mapping["reference"] < len(row) else None
        qty_val = row[mapping["quantity"]] if mapping["quantity"] < len(row) else None
        date_val = row[mapping["fifo_date"]] if mapping["fifo_date"] < len(row) else None
        blocked_val = row[mapping["blocked"]] if "blocked" in mapping and mapping["blocked"] < len(row) else None
        is_blocked = parse_blocked(blocked_val)

        label = parse_label(label_val)
        if not label:
            result.invalid_label_count += 1
            result.errors.append(RowError(row=row_idx, reason="ETİKET boş veya geçersiz", error_type="label"))
            continue

        reference = parse_reference(ref_val)
        if not reference:
            result.invalid_reference_count += 1
            result.errors.append(RowError(row=row_idx, reason="REFERANS boş veya geçersiz", error_type="reference"))
            continue

        quantity = parse_quantity(qty_val)
        if quantity is None:
            result.invalid_quantity_count += 1
            result.errors.append(RowError(row=row_idx, reason="MİKTAR geçersiz", error_type="quantity"))
            continue

        fifo_date = parse_fifo_datetime(date_val)
        if fifo_date is None:
            result.invalid_fifo_date_count += 1
            fifo_hdr = custom_headers.get("fifo_date_header") or "X98FIFO_TARIH"
            result.errors.append(RowError(row=row_idx, reason=f"{fifo_hdr} geçersiz", error_type="fifo_date"))
            continue

        if label in seen_labels:
            result.duplicate_labels.append(label)
            result.errors.append(RowError(row=row_idx, reason=f"Duplicate etiket: {label}", error_type="duplicate"))
            continue

        seen_labels.add(label)
        if label in existing_by_label:
            existing_inv = existing_by_label[label]
            existing_inv.reference = reference
            existing_inv.quantity = quantity
            existing_inv.fifo_date = fifo_date
            existing_inv.blocked = is_blocked
            if replace_existing:
                existing_inv.hidden = False
            result.successful += 1
        else:
            batch.append(InventoryLabel(
                label=label,
                reference=reference,
                quantity=quantity,
                fifo_date=fifo_date,
                blocked=is_blocked,
                hidden=False,
            ))

        if len(result.preview_rows) < PREVIEW_LIMIT:
            result.preview_rows.append(ImportPreviewRow(
                label=label,
                reference=reference,
                quantity=float(quantity),
                fifo_date=format_fifo_datetime(fifo_date),
            ))

        if len(batch) >= BATCH_SIZE:
            db.bulk_save_objects(batch)
            db.commit()
            result.successful += len(batch)
            batch = []

    if batch:
        db.bulk_save_objects(batch)
        db.commit()
        result.successful += len(batch)
    elif result.successful > 0:
        db.commit()

    # replace_existing=True ise yeni Excel'de yer almayan eski stok etiketlerini temizle:
    # - Aktif bir sevkiyatta OKUTULMUŞ (SCANNED/PARTIAL) olan eski etiketlerin ID bağı bozulmasın diye
    #   onları silmek yerine hidden=True yap (böylece okutma kaydı korunur ama yeni FIFO hesabına girmez).
    # - Okutulmamış eski etiketleri ve onların PENDING tahsislerini tamamen sil.
    if replace_existing and existing_by_label:
        removed_inv_ids = [
            inv.id
            for lbl, inv in existing_by_label.items()
            if lbl not in seen_labels
        ]
        if removed_inv_ids:
            scanned_removed_ids = {
                r[0]
                for r in db.query(ShipmentLabel.inventory_label_id)
                .join(Shipment, ShipmentLabel.shipment_id == Shipment.id)
                .filter(
                    ShipmentLabel.inventory_label_id.in_(removed_inv_ids),
                    ShipmentLabel.status.in_([ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL]),
                    Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]),
                )
                .all()
            }
            deletable_ids = [i for i in removed_inv_ids if i not in scanned_removed_ids]
            if deletable_ids:
                db.query(ShipmentLabel).filter(
                    ShipmentLabel.inventory_label_id.in_(deletable_ids),
                    ShipmentLabel.status == ShipmentLabelStatus.PENDING,
                ).delete(synchronize_session=False)
                db.query(ScanLog).filter(
                    ScanLog.inventory_label_id.in_(deletable_ids),
                ).update({ScanLog.inventory_label_id: None}, synchronize_session=False)
                db.query(InventoryLabel).filter(
                    InventoryLabel.id.in_(deletable_ids),
                ).delete(synchronize_session=False)
            if scanned_removed_ids:
                db.query(ShipmentLabel).filter(
                    ShipmentLabel.inventory_label_id.in_(scanned_removed_ids),
                    ShipmentLabel.status == ShipmentLabelStatus.PENDING,
                ).delete(synchronize_session=False)
                db.query(InventoryLabel).filter(
                    InventoryLabel.id.in_(scanned_removed_ids),
                ).update({InventoryLabel.hidden: True}, synchronize_session=False)
            db.commit()

    wb.close()
    return result
