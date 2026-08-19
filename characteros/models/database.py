"""CharacterOS 資料庫連線設定。"""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# 獨立連線字串，禁止覆寫 Narratron State Vault 的 DATABASE_URL
DATABASE_URL = os.getenv(
    "CHARACTEROS_DATABASE_URL",
    "postgresql://narratron:narratron@localhost:5432/characteros",
)

engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """CharacterOS ORM 共用宣告基類；禁止在 orm.py 再宣告一份。"""


def get_db() -> Generator:
    """FastAPI 依賴：取得資料庫 session。用法：`db: Session = Depends(get_db)`。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
