from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    WorkSession, InventoryLabel, Shipment, ShipmentLabel,
    ShipmentDateQuota, ScanLog, ShipmentTarget, ExcelHeaderSettings,
    ShipmentStatus, ShipmentLabelStatus,
)
from app.schemas import WorkSessionSchema, WorkSessionCreateSchema, WorkSessionUpdateSchema
from app.services.s3_storage import delete_all_session_excel_objects
from app.session_context import DEFAULT_SESSION_ID, session_scope
from app.ws_manager import ws_manager

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def ensure_default_work_session(db: Session) -> WorkSession:
    """Varsayılan 1. oturumun ('1. Oturum (Ana Proje)') her zaman mevcut olmasını sağlar."""
    from sqlalchemy import text
    WorkSession.__table__.create(bind=db.get_bind(), checkfirst=True)
    row = db.query(WorkSession).filter(WorkSession.id == DEFAULT_SESSION_ID).first()
    if row is None:
        now = datetime.utcnow()
        row = WorkSession(
            id=DEFAULT_SESSION_ID,
            name="1. Oturum (Ana Proje)",
            staff_name="Genel",
            description="Varsayılan ortak çalışma oturumu",
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        # PostgreSQL'de açık id=1 eklemesi sonrası sequence sayacını senkronize et
        if not str(db.get_bind().url).startswith("sqlite"):
            try:
                db.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence('work_sessions', 'id'), "
                        "COALESCE((SELECT MAX(id) FROM work_sessions), 1), true)"
                    )
                )
                db.commit()
            except Exception:
                db.rollback()
    return row


def list_work_sessions_with_stats(db: Session) -> list[WorkSessionSchema]:
    """Tüm oturumları ve her oturumun canlı stok/sevkiyat/bağlı cihaz özetini tek toplu sorguyla döner."""
    ensure_default_work_session(db)
    sessions = db.query(WorkSession).order_by(WorkSession.id.asc()).all()

    # 1. Her oturumdaki aktif stok etiket sayısı (ignore_session_filter=True ile tek sorguda)
    stock_counts: dict[int, int] = {}
    stock_rows = (
        db.query(InventoryLabel.session_id, func.count(InventoryLabel.id))
        .execution_options(ignore_session_filter=True)
        .filter(InventoryLabel.hidden.is_(False))
        .group_by(InventoryLabel.session_id)
        .all()
    )
    for sid, cnt in stock_rows:
        stock_counts[int(sid or DEFAULT_SESSION_ID)] = int(cnt or 0)

    # 2. Her oturumdaki aktif/tamamlanmış sevkiyatlar ve istenen/okutulan miktarlar
    ship_rows = (
        db.query(
            Shipment.id,
            Shipment.session_id,
            Shipment.group_id,
            Shipment.requested_quantity,
        )
        .execution_options(ignore_session_filter=True)
        .filter(Shipment.status.in_([ShipmentStatus.ACTIVE, ShipmentStatus.COMPLETED]))
        .all()
    )

    groups_by_session: dict[int, set[int]] = defaultdict(set)
    req_by_session: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    sid_by_shipment_id: dict[int, int] = {}
    for sh_id, sess_id, gid, req_q in ship_rows:
        s_key = int(sess_id or DEFAULT_SESSION_ID)
        groups_by_session[s_key].add(int(gid if gid is not None else sh_id))
        req_by_session[s_key] += Decimal(req_q or 0)
        sid_by_shipment_id[int(sh_id)] = s_key

    scanned_by_session: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    if sid_by_shipment_id:
        sl_rows = (
            db.query(ShipmentLabel.shipment_id, func.sum(ShipmentLabel.scanned_quantity))
            .execution_options(ignore_session_filter=True)
            .filter(
                ShipmentLabel.shipment_id.in_(list(sid_by_shipment_id.keys())),
                ShipmentLabel.status.in_([ShipmentLabelStatus.SCANNED, ShipmentLabelStatus.PARTIAL]),
            )
            .group_by(ShipmentLabel.shipment_id)
            .all()
        )
        for sh_id, sc_sum in sl_rows:
            s_key = sid_by_shipment_id.get(int(sh_id), DEFAULT_SESSION_ID)
            scanned_by_session[s_key] += Decimal(sc_sum or 0)

    out: list[WorkSessionSchema] = []
    for ws in sessions:
        sid = int(ws.id)
        out.append(
            WorkSessionSchema(
                id=sid,
                name=ws.name,
                staff_name=ws.staff_name,
                description=ws.description,
                total_labels=stock_counts.get(sid, 0),
                shipment_count=len(groups_by_session.get(sid, set())),
                scanned_quantity=float(scanned_by_session.get(sid, Decimal("0"))),
                requested_quantity=float(req_by_session.get(sid, Decimal("0"))),
                connected_clients=ws_manager.room_count(sid),
                created_at=ws.created_at.strftime("%d.%m.%Y %H:%M") if ws.created_at else "",
                updated_at=ws.updated_at.strftime("%d.%m.%Y %H:%M") if ws.updated_at else "",
            )
        )
    return out


@router.get("", response_model=list[WorkSessionSchema])
def get_sessions(db: Session = Depends(get_db)):
    """Tüm çalışma oturumlarını (projeleri/personel odalarını) listeler."""
    return list_work_sessions_with_stats(db)


@router.post("", response_model=WorkSessionSchema)
def create_session(payload: WorkSessionCreateSchema, db: Session = Depends(get_db)):
    """Yeni bir çalışma oturumu (örn: 'Personel 1 - X Projesi') oluşturur."""
    ensure_default_work_session(db)
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Oturum / Proje adı boş olamaz.")

    if not str(db.get_bind().url).startswith("sqlite"):
        from sqlalchemy import text
        try:
            db.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('work_sessions', 'id'), "
                    "COALESCE((SELECT MAX(id) FROM work_sessions), 1), true)"
                )
            )
            db.commit()
        except Exception:
            db.rollback()

    staff = (payload.staff_name or "").strip() or None
    desc = (payload.description or "").strip() or None
    now = datetime.utcnow()

    ws = WorkSession(
        name=name[:200],
        staff_name=staff[:150] if staff else None,
        description=desc[:300] if desc else None,
        created_at=now,
        updated_at=now,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)

    all_sessions = list_work_sessions_with_stats(db)
    ws_manager.broadcast_sync(
        "sessions_updated",
        [s.model_dump() for s in all_sessions],
        all_rooms=True,
    )
    created = next((s for s in all_sessions if s.id == ws.id), None)
    return created or all_sessions[-1]


@router.patch("/{session_id}", response_model=WorkSessionSchema)
def update_session(
    session_id: int,
    payload: WorkSessionUpdateSchema,
    db: Session = Depends(get_db),
):
    """Mevcut bir çalışma oturumunun adını veya personel bilgisini günceller."""
    ensure_default_work_session(db)
    ws = db.query(WorkSession).filter(WorkSession.id == session_id).first()
    if ws is None:
        raise HTTPException(status_code=404, detail="Oturum bulunamadı")

    if payload.name is not None:
        clean_name = payload.name.strip()
        if not clean_name:
            raise HTTPException(status_code=400, detail="Oturum adı boş olamaz")
        ws.name = clean_name[:200]

    if payload.staff_name is not None:
        ws.staff_name = payload.staff_name.strip()[:150] or None

    if payload.description is not None:
        ws.description = payload.description.strip()[:300] or None

    ws.updated_at = datetime.utcnow()
    db.commit()

    all_sessions = list_work_sessions_with_stats(db)
    ws_manager.broadcast_sync(
        "sessions_updated",
        [s.model_dump() for s in all_sessions],
        all_rooms=True,
    )
    updated = next((s for s in all_sessions if s.id == session_id), None)
    if not updated:
        raise HTTPException(status_code=404, detail="Oturum bulunamadı")
    return updated


@router.delete("/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    """
    Bir çalışma oturumunu ve o oturuma ait tüm stok, sevkiyat, okutma ve Mini S3 Excel
    dosyalarını temizler. Varsayılan 1. oturum silinirse kaydı sıfırlanır (oturum kalır).
    """
    ensure_default_work_session(db)
    ws = db.query(WorkSession).filter(WorkSession.id == session_id).first()
    if ws is None:
        raise HTTPException(status_code=404, detail="Oturum bulunamadı")

    with session_scope(session_id):
        sids = [r[0] for r in db.query(Shipment.id).all()]
        if sids:
            db.query(ShipmentDateQuota).filter(ShipmentDateQuota.shipment_id.in_(sids)).delete(synchronize_session=False)
            db.query(ShipmentLabel).filter(ShipmentLabel.shipment_id.in_(sids)).delete(synchronize_session=False)
        db.query(ScanLog).delete(synchronize_session=False)
        db.query(Shipment).delete(synchronize_session=False)
        db.query(ShipmentTarget).delete(synchronize_session=False)
        db.query(InventoryLabel).delete(synchronize_session=False)
        db.query(ExcelHeaderSettings).delete(synchronize_session=False)
        db.commit()
        delete_all_session_excel_objects(db, session_id=session_id)

    if session_id != DEFAULT_SESSION_ID:
        db.delete(ws)
        db.commit()

    all_sessions = list_work_sessions_with_stats(db)
    ws_manager.broadcast_sync(
        "sessions_updated",
        [s.model_dump() for s in all_sessions],
        all_rooms=True,
    )
    return {
        "deleted": True,
        "session_id": session_id,
        "sessions": [s.model_dump() for s in all_sessions],
    }
