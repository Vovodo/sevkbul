import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.services.target_service import add_target
from app.utils.excel_parser import (
    find_shipment_column_mapping,
    normalize_header,
    parse_reference,
    parse_quantity,
)


UNSUITABLE_SHIPMENT = (
    "Bu dosya sevkiyat formatına uygun değil. "
    "Solda referans, sağda miktar (sayı) olmalı."
)

_NUMBER_TEXT = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")


def shipment_name_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    base = os.path.basename(str(filename).replace("\\", "/")).strip()
    stem = os.path.splitext(base)[0].strip()
    return stem[:200] if stem else None


def _cell(row, index):
    if row is None or index >= len(row):
        return None
    return row[index]


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _skip_left(reference: str) -> bool:
    norm = normalize_header(reference)
    if not norm:
        return True
    if norm in {
        "REFERANS", "REF", "REFERENCE", "MIKTAR", "ADET", "MIKTARI",
        "SEVKIYAT_MIKTARI", "SEVKIYATMIKTARI", "ETIKET", "BARKOD", "LABEL",
        "NOT", "ACIKLAMA", "TARIH",
    }:
        return True
    return "REFERANS" in norm or "MIKTAR" in norm or "FIFO" in norm or norm.startswith("ETIKET")


def _is_written_text(value) -> bool:
    """Miktar hücresi harf veya yazı mı. Boş hücre ve düz sayı yazı sayılmaz."""
    if _is_blank(value) or isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return False
    if isinstance(value, (datetime, date)):
        return True
    text = str(value).strip()
    if not text or parse_quantity(value) is not None:
        return False
    compact = text.replace(" ", "")
    if _NUMBER_TEXT.fullmatch(compact):
        try:
            Decimal(compact.replace(",", "."))
            return False
        except InvalidOperation:
            return True
    return True


def has_reference_with_written_quantity(rows: list) -> bool:
    """Sol sütun referans, sağ sütun sayı yerine yazı olan satır var mı."""
    width = max((len(row) for row in rows), default=0)
    for col in range(max(width - 1, 0)):
        for row in rows:
            reference = parse_reference(_cell(row, col))
            if not reference or _skip_left(reference):
                continue
            if _is_written_text(_cell(row, col + 1)):
                return True
    return False


def locate_shipment_columns(rows: list) -> tuple[int, int, int] | None:
    """Referans ve miktar sütunlarını bulur.

    Başlık varsa onu kullanır. Başlık yoksa sayfanın herhangi bir yerindeki
    bitişik çifti alır: sol sütun referans, sağ sütun miktar.
    """
    for row_index, row in enumerate(rows):
        mapping = find_shipment_column_mapping(list(row))
        ref_idx = mapping.get("reference")
        qty_idx = mapping.get("quantity")
        if ref_idx is None or qty_idx is None or qty_idx <= ref_idx:
            continue
        for later in rows[row_index + 1:]:
            if parse_reference(_cell(later, ref_idx)) and parse_quantity(_cell(later, qty_idx)) is not None:
                return ref_idx, qty_idx, row_index + 1

    width = max((len(row) for row in rows), default=0)
    best: tuple[int, int] | None = None
    for col in range(max(width - 1, 0)):
        score = 0
        for row in rows:
            reference = parse_reference(_cell(row, col))
            quantity = parse_quantity(_cell(row, col + 1))
            if not reference or quantity is None:
                continue
            if normalize_header(reference) in {"REFERANS", "REF", "REFERENCE"}:
                continue
            score += 1
        if score and (best is None or score > best[0]):
            best = (score, col)
    if best is None:
        return None
    return best[1], best[1] + 1, 0


@dataclass
class ShipmentRowError:
    row: int
    reason: str


@dataclass
class ShipmentTargetImportResult:
    total_rows: int = 0
    successful: int = 0
    errors: list[ShipmentRowError] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)
    targets: list[dict] = field(default_factory=list)


def import_shipment_targets_excel(
    db: Session,
    file_content: bytes,
    replace: bool = True,
    filename: str | None = None,
) -> ShipmentTargetImportResult:
    """Sevkiyat Excelini hedef listesine aktarır (FIFO henüz hesaplanmaz)."""
    from app.models import ShipmentTarget

    result = ShipmentTargetImportResult()
    source_name = shipment_name_from_filename(filename)

    try:
        wb = load_workbook(BytesIO(file_content), read_only=True, data_only=True)
    except Exception:
        result.errors.append(ShipmentRowError(row=0, reason="Excel dosyası açılamadı"))
        return result

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        result.errors.append(ShipmentRowError(row=0, reason="Excel dosyası boş"))
        wb.close()
        return result

    located = locate_shipment_columns(rows)
    if located is None:
        if has_reference_with_written_quantity(rows):
            result.errors.append(ShipmentRowError(row=0, reason=UNSUITABLE_SHIPMENT))
        else:
            result.missing_columns.extend(["REFERANS", "MİKTAR"])
        wb.close()
        return result

    ref_idx, qty_idx, start = located
    header_mode = start > 0

    if replace:
        db.query(ShipmentTarget).delete(synchronize_session=False)
        existing_by_key: dict[str, ShipmentTarget] = {}
    else:
        existing_rows = db.query(ShipmentTarget).order_by(ShipmentTarget.id).all()
        existing_by_key = {r.reference.strip().upper(): r for r in existing_rows}

    new_rows_by_key: dict[str, ShipmentTarget] = {}
    ordered_new: list[ShipmentTarget] = []

    for row_idx, row in enumerate(rows[start:], start=start + 1):
        reference = parse_reference(_cell(row, ref_idx))
        quantity = parse_quantity(_cell(row, qty_idx))
        if not reference and quantity is None:
            continue
        result.total_rows += 1
        if not reference:
            if header_mode:
                result.errors.append(ShipmentRowError(row=row_idx, reason="REFERANS boş"))
            continue
        if quantity is None:
            if header_mode:
                result.errors.append(ShipmentRowError(row=row_idx, reason="MİKTAR geçersiz"))
            continue

        ref_clean = reference.strip()
        if not ref_clean:
            if header_mode:
                result.errors.append(ShipmentRowError(row=row_idx, reason="REFERANS boş"))
            continue
        if quantity <= 0:
            if header_mode:
                result.errors.append(ShipmentRowError(row=row_idx, reason="Miktar geçersiz"))
            continue

        rkey = ref_clean.upper()
        if rkey in existing_by_key:
            ex = existing_by_key[rkey]
            ex.target_quantity = Decimal(ex.target_quantity) + Decimal(quantity)
            if source_name and not ex.source_name:
                ex.source_name = source_name
        elif rkey in new_rows_by_key:
            nw = new_rows_by_key[rkey]
            nw.target_quantity = Decimal(nw.target_quantity) + Decimal(quantity)
        else:
            nw = ShipmentTarget(reference=ref_clean, target_quantity=quantity, source_name=source_name)
            new_rows_by_key[rkey] = nw
            ordered_new.append(nw)
        result.successful += 1

    if ordered_new:
        db.add_all(ordered_new)
    db.commit()

    all_targets = db.query(ShipmentTarget).order_by(ShipmentTarget.id).all()
    result.targets = [
        {
            "id": t.id,
            "reference": t.reference,
            "target_quantity": float(t.target_quantity),
        }
        for t in all_targets
    ]

    if result.successful == 0 and not result.errors:
        result.errors.append(ShipmentRowError(row=0, reason="Sevkiyat satırı bulunamadı"))

    wb.close()
    return result
