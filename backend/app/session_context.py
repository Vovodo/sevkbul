"""
Çoklu Oturum (Multi-Session / Multi-Workspace) Bağlam Yöneticisi.
Her HTTP isteği ve arka plan işi kendi aktif 'session_id' bağlamında çalışır.
Varsayılan oturum ID'si 1'dir (geriye dönük %100 uyumluluk).
"""
from contextlib import contextmanager
from contextvars import ContextVar

DEFAULT_SESSION_ID = 1

_current_session_id: ContextVar[int] = ContextVar("current_session_id", default=DEFAULT_SESSION_ID)


def get_current_session_id() -> int:
    val = _current_session_id.get()
    return int(val) if val and int(val) > 0 else DEFAULT_SESSION_ID


def set_current_session_id(session_id: int | None):
    sid = int(session_id) if session_id and int(session_id) > 0 else DEFAULT_SESSION_ID
    return _current_session_id.set(sid)


def reset_current_session_id(token) -> None:
    _current_session_id.reset(token)


@contextmanager
def session_scope(session_id: int | None):
    token = set_current_session_id(session_id)
    try:
        yield get_current_session_id()
    finally:
        reset_current_session_id(token)
