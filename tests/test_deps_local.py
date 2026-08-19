"""deps 與 DB 可用性切換測試。"""

from __future__ import annotations

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from characteros.deps import resolve_character_backend
from characteros.storage.db_availability import mark_database_unavailable
from characteros.storage.local_characters import LocalCharacterService


class BrokenSession(Session):
    def execute(self, *_args, **_kwargs):
        raise OperationalError("stmt", {}, Exception("connection refused"))


def test_resolve_backend_uses_local_when_db_marked_unavailable() -> None:
    mark_database_unavailable()
    backend = resolve_character_backend(BrokenSession())
    assert isinstance(backend, LocalCharacterService)
