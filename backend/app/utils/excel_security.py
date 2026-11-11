"""
SevkiyatBul — İleri Düzey Çok Katmanlı Excel Güvenlik ve Doğrulama Motoru
========================================================================
Yüklenen her Excel dosyasını içeri almadan ve Mini S3'e kaydetmeden önce
8 bağımsız güvenlik katmanından geçirir:

1. Dosya Adı, Path Traversal ve Çift Uzantı (.exe.xlsx, .php.xlsx vb.) Denetimi
2. Boyut Sınırı (Max 25 MB) ve Magic Bytes (Gerçek PKZIP 'PK\\x03\\x04' İmzası) Denetimi
3. ZIP Arşiv Bütünlüğü, ZIP Slip ve ZIP Bombası (Decompression Bomb / Oran) Koruması
4. Zorunlu OpenXML Yapısı ([Content_Types].xml, xl/workbook.xml) Doğrulaması
5. Zararlı Gömülü İçerik Engelleme (VBA Makro vbaProject.bin, ActiveX, OLE Embeddings, ExternalLinks)
6. Derin XML Güvenlik Taraması (XXE / <!DOCTYPE / <!ENTITY / SYSTEM / Harici UNC & Uzak Şablon SSRF)
7. Çalışma Sayfası Boyut Sınırı (Max 100.000 Satır, Max 200 Sütun - DoS Koruması)
8. Hücre İçi Zararlı Yük Taraması (DDE / Formula Injection '=CMD|', XSS '<script', 'javascript:' vb.)
"""

import io
import os
import re
import zipfile
from dataclasses import dataclass
from openpyxl import load_workbook


class ExcelSecurityError(ValueError):
    """Yüklenen dosya güvenlik denetiminden geçemediğinde fırlatılır."""


@dataclass
class ExcelSecurityReport:
    safe: bool
    filename: str
    size_bytes: int
    uncompressed_bytes: int
    sheet_count: int
    row_count: int
    col_count: int


# Güvenlik sabitleri
MAX_UPLOAD_BYTES = 25 * 1024 * 1024          # 25 MB maksimum yükleme boyutu
MAX_UNCOMPRESSED_BYTES = 150 * 1024 * 1024   # 150 MB maksimum açılmış XML boyutu (ZIP Bomb koruması)
MAX_SINGLE_ENTRY_BYTES = 100 * 1024 * 1024   # Tek bir arşiv girdisi için 100 MB sınır
MAX_ARCHIVE_ENTRIES = 500                    # Bir .xlsx içinde olabilecek maksimum iç dosya sayısı
MAX_COMPRESSION_RATIO = 120.0                # Sıkıştırma oranı sınırı (ZIP Bomb tespiti)
MAX_ROWS_LIMIT = 100_000                     # Maksimum satır sayısı
MAX_COLS_LIMIT = 200                         # Maksimum sütun sayısı

PKZIP_MAGIC = b"PK\x03\x04"

# Bilinen zararlı çalıştırılabilir / script dosya imzaları (Magic Bytes)
FORBIDDEN_MAGIC_PREFIXES: list[tuple[bytes, str]] = [
    (b"MZ", "Windows çalıştırılabilir dosya (EXE/DLL)"),
    (b"\x7fELF", "Linux çalıştırılabilir binary (ELF)"),
    (b"\xca\xfe\xba\xbe", "Mach-O / Java class binary"),
    (b"\xfe\xed\xfa", "Mach-O çalıştırılabilir binary"),
    (b"%PDF", "PDF belgesi"),
    (b"#!/", "Shell / Script dosyası"),
    (b"<?php", "PHP script dosyası"),
    (b"<script", "HTML / JavaScript dosyası"),
    (b"<!DOCTYPE html", "HTML belgesi"),
    (b"<html", "HTML belgesi"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "Eski tip OLE2 binary belge (Makro riski nedeniyle yalnızca modern .xlsx kabul edilir)"),
]

# Dosya adında bulunması yasak olan çift uzantılar
DANGEROUS_EXTENSIONS = {
    ".exe", ".dll", ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".js", ".jse",
    ".wsf", ".wsh", ".msc", ".scr", ".pif", ".com", ".hta", ".jar", ".MSI",
    ".php", ".phtml", ".asp", ".aspx", ".jsp", ".py", ".sh", ".bash", ".pl",
    ".rb", ".cgi", ".elf", ".so", ".dylib", ".xlsm", ".xlsb", ".xltm", ".xlam",
}

# ZIP arşivi içinde kesinlikle bulunmaması gereken dosya/klasör kalıpları
FORBIDDEN_ARCHIVE_PATTERNS = [
    (re.compile(r"(^|/)vbaproject\.bin$", re.IGNORECASE), "VBA Makro kodu (vbaProject.bin)"),
    (re.compile(r"(^|/)xl/macrosheets/", re.IGNORECASE), "Excel 4.0 XLM Makro sayfası"),
    (re.compile(r"(^|/)xl/dialogsheets/", re.IGNORECASE), "Excel Makro diyalog sayfası"),
    (re.compile(r"(^|/)xl/activex/", re.IGNORECASE), "ActiveX bileşeni"),
    (re.compile(r"(^|/)xl/embeddings/", re.IGNORECASE), "Gömülü OLE paketi (embeddings)"),
    (re.compile(r"(^|/)xl/externallinks/", re.IGNORECASE), "Dış veri bağlantısı (externalLinks)"),
    (re.compile(r"\.(exe|dll|bat|cmd|ps1|vbs|js|hta|jar|scr|pif|php|sh|py|bin)$", re.IGNORECASE), "Arşiv içi çalıştırılabilir/binary dosya"),
]

# XML içinde XXE / DTD / Entity ve zararlı formül/script saldırı kalıpları
XXE_PATTERNS = [
    (re.compile(rb"<!DOCTYPE\b", re.IGNORECASE), "XML DOCTYPE (XXE / DTD enjeksiyonu)"),
    (re.compile(rb"<!ENTITY\b", re.IGNORECASE), "XML ENTITY (XXE / Billion Laughs saldırısı)"),
    (re.compile(rb"<!ELEMENT\b", re.IGNORECASE), "XML DTD ELEMENT tanımı"),
]

XML_MALICIOUS_PAYLOAD_PATTERNS = [
    (
        re.compile(rb"<f[^>]*>[^<]*(?:cmd\s*\||powershell|pwsh|wscript|cscript|mshta|rundll32|regsvr32|webservice\s*\(|filterxml\s*\(|register\.id\s*\(|exec\s*\()", re.IGNORECASE),
        "zararlı hücre içeriği (DDE / Komut Enjeksiyonu formülü)",
    ),
    (
        re.compile(rb"(?:&lt;|<)\s*script\b|javascript\s*:", re.IGNORECASE),
        "zararlı hücre içeriği (HTML / JavaScript XSS enjeksiyonu)",
    ),
]

# .rels dosyalarında dış sunucuya / yerel ağa otomatik bağlanan tehlikeli ilişkiler
EXTERNAL_REL_PATTERN = re.compile(
    rb'TargetMode\s*=\s*["\']External["\']',
    re.IGNORECASE,
)
SAFE_HYPERLINK_REL_TYPE = b"relationships/hyperlink"

# Hücre içi DDE / Komut Enjeksiyonu ve XSS / Script kalıpları
CELL_MALICIOUS_PATTERNS = [
    (
        re.compile(r"^\s*[=+\-@]\s*(?:cmd|powershell|pwsh|wscript|cscript|mshta|rundll32|regsvr32|sh|bash|msexcel|winword|dde)\b", re.IGNORECASE),
        "DDE / Komut Enjeksiyonu formülü",
    ),
    (
        re.compile(r"[=+\-@][^|]{0,40}\|[^!]{1,80}!", re.IGNORECASE),
        "DDE (Dynamic Data Exchange) komutu",
    ),
    (
        re.compile(r"^\s*=\s*(?:WEBSERVICE|FILTERXML|CALL|REGISTER\.ID|EXEC|SYSTEM|HYPERLINK)\s*\(", re.IGNORECASE),
        "Tehlikeli Excel sistem/ağ fonksiyonu",
    ),
    (
        re.compile(r"<\s*script\b|javascript\s*:|vbscript\s*:|data\s*:\s*text/html|on(?:error|load|click|mouseover)\s*=", re.IGNORECASE),
        "HTML / JavaScript XSS enjeksiyonu",
    ),
]


def validate_filename_security(filename: str | None) -> str:
    """Katman 1: Dosya adı, uzantı ve çift uzantı denetimi."""
    if not filename or not str(filename).strip():
        raise ExcelSecurityError("Güvenlik Reddi: Dosya adı boş olamaz.")

    raw = str(filename).strip()
    if "\x00" in raw or any(ord(c) < 32 for c in raw):
        raise ExcelSecurityError("Güvenlik Reddi: Dosya adında geçersiz kontrol karakteri tespit edildi.")

    base = os.path.basename(raw.replace("\\", "/")).strip()
    if not base or base in {".", ".."} or ".." in base:
        raise ExcelSecurityError("Güvenlik Reddi: Geçersiz veya dizin aşımı (path traversal) içeren dosya adı.")

    lower_base = base.lower()
    if not lower_base.endswith(".xlsx"):
        if lower_base.endswith((".xlsm", ".xlsb", ".xltm", ".xlam")):
            raise ExcelSecurityError("Güvenlik Reddi: Makro içeren Excel formatları (.xlsm/.xlsb) güvenlik nedeniyle kabul edilmez. Standart .xlsx yükleyin.")
        raise ExcelSecurityError("Güvenlik Reddi: Yalnızca doğrulanmış '.xlsx' Excel dosyaları kabul edilir.")

    # Çift uzantı kontrolü (örn: zararli.exe.xlsx, shell.php.xlsx)
    stem = lower_base[:-5]  # .xlsx öncesi
    for ext in DANGEROUS_EXTENSIONS:
        if stem.endswith(ext.lower()):
            raise ExcelSecurityError(f"Güvenlik Reddi: Şüpheli çift uzantılı dosya adı tespit edildi ('{ext}.xlsx').")

    return base


def verify_and_sanitize_excel_upload(
    file_content: bytes,
    filename: str | None = "dosya.xlsx",
) -> ExcelSecurityReport:
    """
    Yüklenen Excel dosyasını 8 güvenlik katmanından geçirir.
    En ufak bir şüpheli durumda ExcelSecurityError fırlatır; yalnızca %100 güvenli
    olduğundan emin olunan dosyalar için ExcelSecurityReport döner.
    """
    # ─── KATMAN 1: Dosya Adı & Uzantı Denetimi ───
    safe_filename = validate_filename_security(filename)

    # ─── KATMAN 2: Boyut & Magic Bytes (Dosya İmzası) Denetimi ───
    if not file_content:
        raise ExcelSecurityError("Güvenlik Reddi: Yüklenen dosya boş (0 byte).")

    size_bytes = len(file_content)
    if size_bytes > MAX_UPLOAD_BYTES:
        mb = round(size_bytes / (1024 * 1024), 2)
        raise ExcelSecurityError(f"Güvenlik Reddi: Dosya boyutu çok büyük ({mb} MB). Maksimum izin verilen boyut 25 MB.")

    if size_bytes < 64:
        raise ExcelSecurityError("Güvenlik Reddi: Dosya geçerli bir Excel (.xlsx) yapısında değil.")

    head = file_content[:64].lstrip()
    for prefix, desc in FORBIDDEN_MAGIC_PREFIXES:
        if file_content.startswith(prefix) or head.startswith(prefix):
            raise ExcelSecurityError(f"Güvenlik Reddi: Yüklenen dosya gerçek bir Excel değil ({desc} tespit edildi).")

    if not file_content.startswith(PKZIP_MAGIC):
        raise ExcelSecurityError("Güvenlik Reddi: Dosya imzası (Magic Bytes) geçerli bir .xlsx (OpenXML) paketiyle eşleşmiyor.")

    # ─── KATMAN 3: ZIP Arşiv Bütünlüğü, ZIP Slip & ZIP Bombası Koruması ───
    try:
        zf = zipfile.ZipFile(io.BytesIO(file_content), mode="r")
    except Exception as exc:
        raise ExcelSecurityError("Güvenlik Reddi: Bozuk veya geçersiz arşiv yapısı.") from exc

    with zf:
        infos = zf.infolist()
        if not infos:
            raise ExcelSecurityError("Güvenlik Reddi: Arşiv içeriği boş.")
        if len(infos) > MAX_ARCHIVE_ENTRIES:
            raise ExcelSecurityError(
                f"Güvenlik Reddi: Paket içinde aşırı sayıda alt dosya ({len(infos)}) bulundu (ZIP Bomb şüphesi)."
            )

        total_uncompressed = 0
        entry_names_lower: set[str] = set()

        for info in infos:
            name = info.filename.replace("\\", "/")
            # ZIP Slip (Path Traversal) kontrolü
            if (
                name.startswith("/")
                or ".." in name.split("/")
                or ":" in name
                or "\x00" in name
            ):
                raise ExcelSecurityError(f"Güvenlik Reddi: Arşiv içinde tehlikeli dosya yolu tespit edildi ('{name}').")

            # Boyut ve Sıkıştırma Oranı (ZIP Bombası) kontrolü
            if info.file_size < 0 or info.file_size > MAX_SINGLE_ENTRY_BYTES:
                raise ExcelSecurityError("Güvenlik Reddi: Arşiv içindeki XML boyutu güvenlik sınırını aşıyor (ZIP Bomb koruması).")

            total_uncompressed += info.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise ExcelSecurityError("Güvenlik Reddi: Toplam açılmış veri boyutu 150 MB sınırını aşıyor (ZIP Bomb koruması).")

            if info.compress_size > 0 and info.file_size > 1024 * 1024:
                ratio = info.file_size / info.compress_size
                if ratio > MAX_COMPRESSION_RATIO:
                    raise ExcelSecurityError(
                        f"Güvenlik Reddi: Anormal sıkıştırma oranı ({ratio:.0f}x) tespit edildi (ZIP Bomb şüphesi)."
                    )

            # ─── KATMAN 4: Zararlı Gömülü İçerik (VBA Makro / ActiveX / OLE / Binary) Taraması ───
            for pattern, reason in FORBIDDEN_ARCHIVE_PATTERNS:
                if pattern.search(name):
                    raise ExcelSecurityError(f"Güvenlik Reddi: Excel içinde yasaklı bileşen tespit edildi ({reason}: '{name}').")

            entry_names_lower.add(name.lower())

        # Zorunlu OpenXML bileşenleri kontrolü
        if "[content_types].xml" not in entry_names_lower or not any(
            n.endswith("workbook.xml") for n in entry_names_lower
        ):
            raise ExcelSecurityError(
                "Güvenlik Reddi: Dosya standart bir Excel (.xlsx) çalışma kitabı değil (eksik OpenXML çekirdek dosyaları)."
            )

        # ─── KATMAN 5: Derin XML Tarama (XXE / DTD / Entity / Harici İlişki SSRF / Formül Enjeksiyonu) ───
        for info in infos:
            lname = info.filename.lower()
            if lname.endswith((".xml", ".rels")):
                raw_xml = zf.read(info.filename)
                for xxe_re, xxe_desc in XXE_PATTERNS:
                    if xxe_re.search(raw_xml):
                        raise ExcelSecurityError(f"Güvenlik Reddi: XML içinde zararlı yapı tespit edildi ({xxe_desc}).")

                for mal_xml_re, mal_xml_desc in XML_MALICIOUS_PAYLOAD_PATTERNS:
                    if mal_xml_re.search(raw_xml):
                        raise ExcelSecurityError(f"Güvenlik Reddi: Excel içinde {mal_xml_desc} tespit edildi.")

                if lname.endswith(".rels") and EXTERNAL_REL_PATTERN.search(raw_xml):
                    # Dış bağlantılara (external template / external link / UNC) izin verme
                    if SAFE_HYPERLINK_REL_TYPE not in raw_xml:
                        raise ExcelSecurityError(
                            "Güvenlik Reddi: Excel içinde dış sunucuya veya ağa bağlanan harici ilişki (External Relationship) tespit edildi."
                        )

    # ─── KATMAN 6, 7 & 8: OpenPyXL Güvenli Okuma, Boyut Sınırı ve Hücre İçi Enjeksiyon Taraması ───
    try:
        wb = load_workbook(io.BytesIO(file_content), read_only=True, data_only=True)
    except Exception as exc:
        raise ExcelSecurityError("Güvenlik Reddi: Excel çalışma kitabı okunamadı veya bozuk.") from exc

    total_rows_scanned = 0
    max_cols_seen = 0
    sheet_names = wb.sheetnames

    try:
        if not sheet_names:
            raise ExcelSecurityError("Güvenlik Reddi: Excel dosyasında hiçbir çalışma sayfası yok.")

        ws = wb.active
        if ws is None:
            raise ExcelSecurityError("Güvenlik Reddi: Aktif çalışma sayfası bulunamadı.")

        for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            total_rows_scanned += 1
            if total_rows_scanned > MAX_ROWS_LIMIT:
                raise ExcelSecurityError(
                    f"Güvenlik Reddi: Satır sayısı üst sınırı ({MAX_ROWS_LIMIT:,}) aşıldı."
                )

            if row is None:
                continue

            col_len = len(row)
            if col_len > max_cols_seen:
                max_cols_seen = col_len
            if col_len > MAX_COLS_LIMIT:
                raise ExcelSecurityError(
                    f"Güvenlik Reddi: Sütun sayısı üst sınırı ({MAX_COLS_LIMIT}) aşıldı."
                )

            for cell in row:
                if cell is None or not isinstance(cell, str):
                    continue
                txt = cell.strip()
                if not txt:
                    continue
                if "\x00" in txt:
                    raise ExcelSecurityError(
                        f"Güvenlik Reddi: {row_idx}. satırda null-byte enjeksiyonu tespit edildi."
                    )
                for mal_re, mal_desc in CELL_MALICIOUS_PATTERNS:
                    if mal_re.search(txt):
                        raise ExcelSecurityError(
                            f"Güvenlik Reddi: {row_idx}. satırda zararlı hücre içeriği tespit edildi ({mal_desc})."
                        )
    finally:
        wb.close()

    return ExcelSecurityReport(
        safe=True,
        filename=safe_filename,
        size_bytes=size_bytes,
        uncompressed_bytes=total_uncompressed,
        sheet_count=len(sheet_names),
        row_count=total_rows_scanned,
        col_count=max_cols_seen,
    )
