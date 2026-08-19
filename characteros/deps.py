"""FastAPI 依賴：依 DB 可用性選擇 PostgreSQL 或本機 charpass。"""

from __future__ import annotations

from typing import Union

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from fastapi import Depends
from sqlalchemy.orm import Session

from characteros.models.database import get_db
from characteros.services.characters import CharacterService
from characteros.storage.db_availability import is_database_available, mark_database_unavailable
from characteros.storage.local_characters import LocalCharacterService

CharacterBackend = Union[CharacterService, LocalCharacterService]


def resolve_character_backend(db: Session) -> CharacterBackend:
    """優先 PostgreSQL；連線失敗時改讀寫本機 data/charpasses/。"""
    if not is_database_available():
        return LocalCharacterService()
    try:
        db.execute(text("SELECT 1"))
        return CharacterService(db)
    except SQLAlchemyError:
        mark_database_unavailable()
        return LocalCharacterService()


def get_character_backend(db: Session = Depends(get_db)) -> CharacterBackend:
    """FastAPI Depends：DB 不可用時自動切換本機 charpass。"""
    return resolve_character_backend(db)
