"""FIFO yeniden hesaplamayı istek dışında çalıştırır.

Her çalışma oturumu (session_id) kendi bağımsız hesaplama durumuna sahiptir;
farklı personeller aynı anda kendi oturumlarında yeniden hesaplama başlatabilir.
"""
import threading
import time

from app.services.shipment_service import recalculate_shipments
from app.session_context import get_current_session_id, session_scope
from app.ws_manager import ws_manager

_lock = threading.Lock()
_job_counter = 0
_states: dict[int, dict] = {}


def _default_state() -> dict:
    return {
        "job": 0,
        "phase": "idle",
        "percent": 0,
        "done": 0,
        "total": 0,
        "message": "",
        "error": None,
        "updated": 0,
    }


def get_recalculate_status(session_id: int | None = None) -> dict:
    sid = int(session_id) if session_id is not None else get_current_session_id()
    with _lock:
        if sid not in _states:
            _states[sid] = _default_state()
        return dict(_states[sid])


def _publish(sid: int, **kwargs) -> dict:
    with _lock:
        if sid not in _states:
            _states[sid] = _default_state()
        _states[sid].update(kwargs)
        snapshot = dict(_states[sid])
    ws_manager.broadcast_sync("recalculate_progress", snapshot, session_id=sid)
    return snapshot


def _release_later(sid: int, job: int) -> None:
    """Biten işi idle yap. Geç kalan sorgu eski 'tamamlandı' durumunu yeniden açmasın."""
    def _go() -> None:
        time.sleep(2)
        with _lock:
            st = _states.get(sid)
            if not st or st.get("job") != job or st["phase"] not in ("done", "error"):
                return
            st.update({
                "phase": "idle",
                "percent": 0,
                "done": 0,
                "total": 0,
                "message": "",
                "error": None,
            })
    threading.Thread(target=_go, daemon=True, name=f"fifo-recalc-release-{sid}").start()


def _worker(sid: int) -> None:
    from app.database import SessionLocal

    with session_scope(sid):
        db = SessionLocal()
        try:
            def on_progress(done: int, total: int, message: str) -> None:
                percent = 0 if total <= 0 else min(99, int(done * 100 / total))
                _publish(sid, phase="running", done=done, total=total, percent=percent, message=message, error=None)

            result = recalculate_shipments(db, on_progress=on_progress)
            snapshot = _publish(
                sid,
                phase="done",
                percent=100,
                done=result["updated"],
                total=result["updated"],
                message="Hesaplama tamamlandı",
                error=None,
                updated=result["updated"],
            )
            _release_later(sid, snapshot["job"])
            from app.routers.operation import _broadcast_full_status
            _broadcast_full_status(db, "recalculate", {"updated": result["updated"]})
        except Exception as exc:
            db.rollback()
            snapshot = _publish(sid, phase="error", message="Hesaplama tamamlanamadı", error=str(exc))
            _release_later(sid, snapshot["job"])
        finally:
            db.close()


def start_recalculate(session_id: int | None = None) -> str:
    global _job_counter
    sid = int(session_id) if session_id is not None else get_current_session_id()
    with _lock:
        if sid not in _states:
            _states[sid] = _default_state()
        if _states[sid]["phase"] == "running":
            return "running"
        _job_counter += 1
        _states[sid].update({
            "job": _job_counter,
            "phase": "running",
            "percent": 0,
            "done": 0,
            "total": 0,
            "message": "Hazırlanıyor",
            "error": None,
            "updated": 0,
        })
    threading.Thread(target=_worker, args=(sid,), daemon=True, name=f"fifo-recalculate-{sid}").start()
    return "started"
