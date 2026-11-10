import hashlib
import os
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import StoredExcelFile

EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Backend kök dizini altında storage/s3 klasörü
BASE_STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage" / "s3"


def _sanitize_filename(filename: str | None, fallback: str = "dosya.xlsx") -> str:
    if not filename:
        return fallback
    base = os.path.basename(str(filename).replace("\\", "/")).strip()
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", base).strip()
    return cleaned[:200] if cleaned else fallback


def _slot_dir(slot: str) -> Path:
    safe_slot = re.sub(r"[^a-z0-9_\-]", "", slot.lower()) or "default"
    d = BASE_STORAGE_DIR / safe_slot
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cleanup_slot_files(slot: str, old_local_path: str | None = None) -> None:
    """Belirtilen slot klasöründeki tüm eski Excel dosyalarını diskten siler (şişmeyi önler)."""
    slot_folder = _slot_dir(slot)
    for item in slot_folder.iterdir():
        if item.is_file():
            try:
                item.unlink()
            except OSError:
                pass

    if old_local_path:
        try:
            abs_old = BASE_STORAGE_DIR.parent.parent / old_local_path
            if abs_old.is_file():
                abs_old.unlink()
        except OSError:
            pass


def put_excel_object(
    db: Session,
    slot: str,
    filename: str | None,
    content: bytes,
    row_count: int = 0,
    content_type: str = EXCEL_MIME,
) -> StoredExcelFile:
    """
    Yüklenen Excel dosyasını Mini S3 alanına kaydeder ve konum/içerik bilgisini PostgreSQL'e yazar.
    Aynı slot ('stock' veya 'shipment') için önceki dosya hem diskten hem veritabanından silinir.
    """
    StoredExcelFile.__table__.create(bind=db.get_bind(), checkfirst=True)

    safe_name = _sanitize_filename(filename, fallback=f"{slot}.xlsx")
    slot_folder = _slot_dir(slot)

    existing = db.query(StoredExcelFile).filter(StoredExcelFile.slot == slot).first()
    _cleanup_slot_files(slot, existing.local_path if existing else None)

    target_file = slot_folder / safe_name
    target_file.write_bytes(content)

    rel_path = f"storage/s3/{slot}/{safe_name}"
    s3_key = f"s3://sevkbul/{slot}/{safe_name}"
    digest = hashlib.sha256(content).hexdigest()
    now = datetime.utcnow()

    if existing is None:
        existing = StoredExcelFile(
            slot=slot,
            original_filename=safe_name,
            storage_key=s3_key,
            local_path=rel_path,
            content_type=content_type or EXCEL_MIME,
            size_bytes=len(content),
            sha256_hash=digest,
            row_count=int(row_count or 0),
            file_data=content,
            uploaded_at=now,
        )
        db.add(existing)
    else:
        existing.original_filename = safe_name
        existing.storage_key = s3_key
        existing.local_path = rel_path
        existing.content_type = content_type or EXCEL_MIME
        existing.size_bytes = len(content)
        existing.sha256_hash = digest
        existing.row_count = int(row_count or 0)
        existing.file_data = content
        existing.uploaded_at = now

    db.commit()
    db.refresh(existing)
    return existing


def get_excel_object(db: Session, slot: str) -> StoredExcelFile | None:
    """Slot'a ait Excel kaydını döner; diskte yoksa PostgreSQL'deki binary veriden diske geri yazar."""
    StoredExcelFile.__table__.create(bind=db.get_bind(), checkfirst=True)
    row = db.query(StoredExcelFile).filter(StoredExcelFile.slot == slot).first()
    if row is None:
        return None

    slot_folder = _slot_dir(slot)
    disk_file = slot_folder / _sanitize_filename(row.original_filename, f"{slot}.xlsx")
    if not disk_file.is_file() and row.file_data:
        try:
            disk_file.write_bytes(row.file_data)
        except OSError:
            pass
    return row


def list_excel_objects(db: Session) -> list[dict]:
    """Kayıtlı tüm Mini S3 Excel dosyalarının üstverisini döner (binary veri hariç)."""
    StoredExcelFile.__table__.create(bind=db.get_bind(), checkfirst=True)
    rows = db.query(StoredExcelFile).order_by(StoredExcelFile.slot.asc()).all()
    out: list[dict] = []
    for r in rows:
        slot_folder = _slot_dir(r.slot)
        disk_file = slot_folder / _sanitize_filename(r.original_filename, f"{r.slot}.xlsx")
        if not disk_file.is_file() and r.file_data:
            try:
                disk_file.write_bytes(r.file_data)
            except OSError:
                pass
        out.append({
            "slot": r.slot,
            "original_filename": r.original_filename,
            "storage_key": r.storage_key,
            "local_path": r.local_path,
            "content_type": r.content_type,
            "size_bytes": r.size_bytes,
            "sha256_hash": r.sha256_hash,
            "row_count": r.row_count,
            "uploaded_at": r.uploaded_at.strftime("%d.%m.%Y %H:%M:%S") if r.uploaded_at else "",
            "exists_on_disk": disk_file.is_file(),
            "download_url": f"/api/inventory/storage/files/{r.slot}/download",
        })
    return out


def delete_excel_object(db: Session, slot: str) -> bool:
    """Slot'taki Excel dosyasını hem diskten hem PostgreSQL'den siler."""
    StoredExcelFile.__table__.create(bind=db.get_bind(), checkfirst=True)
    row = db.query(StoredExcelFile).filter(StoredExcelFile.slot == slot).first()
    _cleanup_slot_files(slot, row.local_path if row else None)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def hydrate_storage_on_startup(db: Session) -> None:
    """
    Sunucu / container yeniden başladığında PostgreSQL'deki Mini S3 kayıtlarını
    yerel disk klasörüne (storage/s3/...) geri yükler.
    """
    try:
        StoredExcelFile.__table__.create(bind=db.get_bind(), checkfirst=True)
        rows = db.query(StoredExcelFile).all()
        for r in rows:
            slot_folder = _slot_dir(r.slot)
            disk_file = slot_folder / _sanitize_filename(r.original_filename, f"{r.slot}.xlsx")
            if not disk_file.is_file() and r.file_data:
                disk_file.write_bytes(r.file_data)
    except Exception:
        pass
