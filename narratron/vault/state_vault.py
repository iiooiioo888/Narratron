"""State Vault（狀態庫）—— PostgreSQL + JSONB；預設本機記憶體後端。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from narratron.vault.memory import InMemoryStore
from narratron.vault.schema import Asset, Entity, Shot, TraceRecord
from narratron.vault.store import VaultStore


class StateVault:
    """狀態庫。Parser 初始化實體；Director 寫入分鏡；資產庫走 `assets` 表。"""

    def __init__(self, store: VaultStore | None = None) -> None:
        self.store: VaultStore = store if store is not None else InMemoryStore()

    @classmethod
    def from_settings(cls, settings: Any | None = None) -> StateVault:
        if settings is None:
            from narratron.api.settings import get_settings

            settings = get_settings()
        backend = str(getattr(settings, "vault_backend", "memory")).strip().lower()
        if backend in {"postgres", "postgresql", "pg"}:
            from narratron.vault.postgres import PostgresStore

            return cls(PostgresStore(settings.database_url))
        return cls(InMemoryStore())

    def init_from_parser(self, entities: list[Entity]) -> None:
        self.upsert_entities(entities)

    def upsert_entities(self, entities: list[Entity]) -> None:
        if entities:
            self.store.upsert_entities(entities)

    def upsert_shots(self, shots: list[Shot]) -> None:
        if shots:
            self.store.upsert_shots(shots)

    def upsert_assets(self, assets: list[Asset]) -> None:
        if assets:
            self.store.upsert_assets(assets)

    def register_reference_image(
        self,
        *,
        asset_id: str,
        uri: str,
        entity_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Asset:
        asset = Asset(
            id=asset_id,
            entity_id=entity_id,
            kind="reference_image",
            uri=uri,
            metadata=metadata or {},
        )
        self.upsert_assets([asset])
        return asset

    def get_entities(self) -> list[Entity]:
        return self.store.get_entities()

    def get_entity(self, entity_id: str) -> Entity | None:
        getter = getattr(self.store, "get_entity", None)
        if callable(getter):
            return getter(entity_id)
        for item in self.store.get_entities():
            if item.id == entity_id:
                return item
        return None

    def delete_entity(self, entity_id: str) -> None:
        deleter = getattr(self.store, "delete_entity", None)
        if callable(deleter):
            deleter(entity_id)
            return
        raise RuntimeError("目前 Vault 後端不支援刪除實體")

    def get_shots(self) -> list[Shot]:
        return self.store.get_shots()

    def get_assets(self) -> list[Asset]:
        return self.store.get_assets()

    def get_traces(self) -> list[TraceRecord]:
        return self.store.get_traces()

    def trace_log(self) -> Any:
        from narratron.vault.trace_log import TraceLog

        return TraceLog(self.store)


@lru_cache(maxsize=1)
def get_default_vault() -> StateVault:
    return StateVault.from_settings()


def reset_default_vault() -> None:
    get_default_vault.cache_clear()
