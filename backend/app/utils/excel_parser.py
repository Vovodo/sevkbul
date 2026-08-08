import unicodedata
import re
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from dateutil import parser as date_parser

# Excel serial date epoch (1900 date system)
_EXCEL_EPOCH = datetime(1899, 12, 30)

REQUIRED_COLUMNS = {
    "ETIKET": "label",
    "REFERANS": "reference",
    "MIKTAR": "quantity",
    "X98FIFO_TARIH": "fifo_date",
}

SHIPMENT_REQUIRED_COLUMNS = {
    "REFERANS": "reference",
}

SHIPMENT_QUANTITY_ALIASES = [
    "SEVKIYAT_MIKTARI",
    "SEVKIYATMIKTARI",
    "MIKTAR",
    "ADET",
    "MIKTARI",
]

_FIFO_DATETIME_PATTERN = re.compile(
    r"^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$"
)


def normalize_header(header: str) -> str:
    if header is None:
        return ""
    text = str(header).strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.upper()
    text = re.sub(r"\s+", "_", text)
    return text


def find_column_mapping(headers: list[Any]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    normalized_headers = {normalize_header(h): idx for idx, h in enumerate(headers) if h is not None}

    # 1. Label column matching
    label_aliases = ["ETIKET", "ETIKET_NO", "ETIKETNO", "BARKOD", "LABEL", "SERINO", "SERI_NO"]
    for alias in label_aliases:
        if alias in normalized_headers:
            mapping["label"] = normalized_headers[alias]
            break
    if "label" not in mapping:
        for norm_h, idx in normalized_headers.items():
            if norm_h.startswith("ETIKET") and "SICIL" not in norm_h and "BASLANGIC" not in norm_h:
                mapping["label"] = idx
                break

    # 2. Reference column matching
    ref_aliases = ["REFERANS", "REFERANS_KODU", "REFERANSKODU", "REF", "REFERENCE", "URUN_KODU"]
    for alias in ref_aliases:
        if alias in normalized_headers:
            mapping["reference"] = normalized_headers[alias]
            break
    if "reference" not in mapping:
        for norm_h, idx in normalized_headers.items():
            if "REFERANS" in norm_h:
                mapping["reference"] = idx
                break

    # 3. Quantity column matching
    qty_aliases = ["MIKTAR", "MIKTARI", "QUANTITY", "QTY", "ADET"]
    for alias in qty_aliases:
        if alias in normalized_headers:
            mapping["quantity"] = normalized_headers[alias]
            break
    if "quantity" not in mapping:
        for norm_h, idx in normalized_headers.items():
            if "MIKTAR" in norm_h or "QUANTITY" in norm_h:
                mapping["quantity"] = idx
                break

    # 4. Fifo date column matching
    fifo_aliases = ["X98FIFO_TARIH", "X98FIFO_TARIHI", "X98FIFOTARIH", "FIFO_TARIH", "FIFO_TARIHI", "FIFOTARIH", "FIFO_DATE", "FIFO"]
    for alias in fifo_aliases:
        if alias in normalized_headers:
            mapping["fifo_date"] = normalized_headers[alias]
            break
    if "fifo_date" not in mapping:
        for norm_h, idx in normalized_headers.items():
            if "FIFO" in norm_h:
                mapping["fifo_date"] = idx
                break

    return mapping


def find_shipment_column_mapping(headers: list[Any]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    normalized_headers = {normalize_header(h): idx for idx, h in enumerate(headers)}

    if "REFERANS" in normalized_headers:
        mapping["reference"] = normalized_headers["REFERANS"]
    else:
        for norm_h, idx in normalized_headers.items():
            if "REFERANS" in norm_h:
                mapping["reference"] = idx
                break

    quantity_idx = None
    for alias in SHIPMENT_QUANTITY_ALIASES:
        if alias in normalized_headers:
            quantity_idx = normalized_headers[alias]
            if alias.startswith("SEVKIYAT"):
                break
    if quantity_idx is None:
        for norm_h, idx in normalized_headers.items():
            if "MIKTAR" in norm_h or "ADET" in norm_h:
                quantity_idx = idx
                break
    if quantity_idx is not None:
        mapping["quantity"] = quantity_idx

    return mapping


def parse_quantity(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        d = Decimal(str(value))
        return d if d > 0 else None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        d = Decimal(text)
        return d if d > 0 else None
    except InvalidOperation:
        return None


def _normalize_datetime(dt: datetime) -> datetime:
    """Microsaniye temizle, saat bilgisini koru."""
    return dt.replace(microsecond=0)


def _parse_excel_serial(value: float) -> datetime | None:
    try:
        serial = float(value)
        if serial <= 0:
            return None
        whole = int(serial)
        fraction = serial - whole
        dt = _EXCEL_EPOCH + timedelta(days=whole)
        if fraction:
            dt = dt + timedelta(seconds=round(fraction * 86400))
        return _normalize_datetime(dt)
    except (ValueError, OverflowError, OSError):
        return None


def _parse_datetime_string(text: str) -> datetime | None:
    text = text.strip()

    m = _FIFO_DATETIME_PATTERN.match(text)
    if m:
        day, month, year, hour, minute, second = m.groups()
        try:
            h = int(hour) if hour is not None else 0
            mi = int(minute) if minute is not None else 0
            s = int(second) if second is not None else 0
            return datetime(int(year), int(month), int(day), h, mi, s)
        except ValueError:
            return None

    try:
        parsed = date_parser.parse(text, dayfirst=True)
        if isinstance(parsed, datetime):
            return _normalize_datetime(parsed)
        return datetime(parsed.year, parsed.month, parsed.day, 0, 0, 0)
    except (ValueError, TypeError, OverflowError):
        return None


def parse_fifo_datetime(value: Any) -> datetime | None:
    """
    X98FIFO_TARIH alanını datetime olarak parse eder.
    Saat bilgisi korunur — yalnızca tarihe indirgenmez.

    Desteklenen formatlar:
    - Python datetime (Excel native)
    - String: DD.MM.YYYY HH:MM veya D.M.YYYY H:MM
    - Excel serial date (float/int)
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return _normalize_datetime(value)

    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, 0, 0, 0)

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return _parse_excel_serial(float(value))

    text = str(value).strip()
    if not text:
        return None

    return _parse_datetime_string(text)


def parse_fifo_date(value: Any) -> datetime | None:
    """Geriye uyumluluk alias."""
    return parse_fifo_datetime(value)


def format_fifo_datetime(dt: datetime) -> str:
    """Görüntüleme: DD.MM.YYYY HH:MM"""
    return dt.strftime("%d.%m.%Y %H:%M")


def parse_label(value: Any) -> str | None:
    """Etiket her zaman string olarak saklanır."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        text = str(value).strip()
        return text if text else None
    text = str(value).strip()
    return text if text else None


def parse_reference(value: Any) -> str | None:
    """Referans string olarak saklanır, numeric'e çevrilmez."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        text = str(value).strip()
    else:
        text = str(value).strip()
    return text if text else None
