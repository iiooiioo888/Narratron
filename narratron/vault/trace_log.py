"""Trace Log（痕跡日誌）。與 State Vault 共用同一儲存後端。"""

from __future__ import annotations

from narratron.vault.memory import InMemoryStore
from narratron.vault.schema import TraceRecord
from narratron.vault.store import VaultStore


class TraceLog:
    """對應表 `trace_log`。"""

    def __init__(self, store: VaultStore | None = None) -> None:
        self.store: VaultStore = store if store is not None else InMemoryStore()

    def append(self, record: TraceRecord) -> None:
        self.store.append_traces([record])

    def append_many(self, records: list[TraceRecord]) -> None:
        if records:
            self.store.append_traces(records)

    def list_for_entity(self, entity_id: str) -> list[TraceRecord]:
        return self.store.list_traces_for_entity(entity_id)

    def list_for_shot(self, shot_id: str) -> list[TraceRecord]:
        return self.store.list_traces_for_shot(shot_id)

    def list_all(self) -> list[TraceRecord]:
        return self.store.get_traces()
