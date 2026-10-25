"""FIFO yeniden hesaplamayı istek dışında çalıştırır.

Uzun stok listesi HTTP isteğini ve arayüzü bekletmez. İlerleme bellekten okunur.
"""
import threading
import time

from app.services.shipment_service import recalculate_shipments
from app.ws_manager import ws_manager

_lock = threading.Lock()
_job = 0
_state = {
    "job": 0,
    "phase": "idle",
    "percent": 0,
    "done": 0,
    "total": 0,
    "message": "",
    "error": None,
    "updated": 0,
}


def get_recalculate_status() -> dict:
    with _lock:
        return dict(_state)


def _publish(**kwargs) -> dict:
    with _lock:
        _state.update(kwargs)
        snapshot = dict(_state)
    ws_manager.broadcast_sync("recalculate_progress", snapshot)
    return snapshot


def _release_later(job: int) -> None:
    """Biten işi idle yap. Geç kalan sorgu eski 'tamamlandı' durumunu yeniden açmasın."""
    def _go() -> None:
        time.sleep(2)
        with _lock:
            if _state.get("job") != job or _state["phase"] not in ("done", "error"):
                return
            _state.update({
                "phase": "idle",
                "percent": 0,
                "done": 0,
                "total": 0,
                "message": "",
                "error": None,
            })
    threading.Thread(target=_go, daemon=True, name="fifo-recalculate-release").start()


def _worker() -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        def on_progress(done: int, total: int, message: str) -> None:
            percent = 0 if total <= 0 else min(99, int(done * 100 / total))
            _publish(phase="running", done=done, total=total, percent=percent, message=message, error=None)

        result = recalculate_shipments(db, on_progress=on_progress)
        snapshot = _publish(
            phase="done",
            percent=100,
            done=result["updated"],
            total=result["updated"],
            message="Hesaplama tamamlandı",
            error=None,
            updated=result["updated"],
        )
        _release_later(snapshot["job"])
        from app.routers.operation import _broadcast_full_status
        _broadcast_full_status(db, "recalculate", {"updated": result["updated"]})
    except Exception as exc:
        db.rollback()
        snapshot = _publish(phase="error", message="Hesaplama tamamlanamadı", error=str(exc))
        _release_later(snapshot["job"])
    finally:
        db.close()


def start_recalculate() -> str:
    global _job
    with _lock:
        if _state["phase"] == "running":
            return "running"
        _job += 1
        _state.update({
            "job": _job,
            "phase": "running",
            "percent": 0,
            "done": 0,
            "total": 0,
            "message": "Hazırlanıyor",
            "error": None,
            "updated": 0,
        })
    threading.Thread(target=_worker, daemon=True, name="fifo-recalculate").start()
    return "started"
