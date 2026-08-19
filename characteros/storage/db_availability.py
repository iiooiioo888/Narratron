"""偵測 PostgreSQL 是否可用，供 API 切換本機 charpass 模式。"""

from __future__ import annotations

from threading import Lock

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from characteros.models.database import engine

_lock = Lock()
_db_available: bool | None = None


def check_database_available() -> bool:
    """主動探測連線；結果會快取至下次 mark/check。"""
    global _db_available
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        available = True
    except SQLAlchemyError:
        available = False
    with _lock:
        _db_available = available
    return available


def is_database_available() -> bool:
    """回傳快取的 DB 可用狀態；首次呼叫會探測。"""
    with _lock:
        cached = _db_available
    if cached is None:
        return check_database_available()
    return cached


def mark_database_unavailable() -> None:
    """查詢失敗後標記為不可用，後續請求走本機 charpass。"""
    global _db_available
    with _lock:
        _db_available = False


def storage_mode_label() -> str:
    return "database" if is_database_available() else "local"
