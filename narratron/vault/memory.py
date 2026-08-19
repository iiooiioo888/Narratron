"""本機記憶體後端：測試與無 Docker 開發預設。非白皮書模組名。"""

from __future__ import annotations

from narratron.vault.schema import Asset, Entity, Shot, TraceRecord


class InMemoryStore:
    def __init__(self) -> None:
        self.entities: dict[str, Entity] = {}
        self.shots: dict[str, Shot] = {}
        self.assets: dict[str, Asset] = {}
        self.traces: dict[str, TraceRecord] = {}

    def upsert_entities(self, entities: list[Entity]) -> None:
        for item in entities:
            self.entities[item.id] = item.model_copy(deep=True)

    def upsert_shots(self, shots: list[Shot]) -> None:
        for item in shots:
            self.shots[item.id] = item.model_copy(deep=True)

    def upsert_assets(self, assets: list[Asset]) -> None:
        for item in assets:
            self.assets[item.id] = item.model_copy(deep=True)

    def append_traces(self, records: list[TraceRecord]) -> None:
        for item in records:
            self.traces[item.id] = item.model_copy(deep=True)

    def get_entities(self) -> list[Entity]:
        return [item.model_copy(deep=True) for item in self.entities.values()]

    def get_entity(self, entity_id: str) -> Entity | None:
        item = self.entities.get(entity_id)
        return item.model_copy(deep=True) if item is not None else None

    def delete_entity(self, entity_id: str) -> None:
        self.entities.pop(entity_id, None)

    def get_shots(self) -> list[Shot]:
        return sorted(
            (item.model_copy(deep=True) for item in self.shots.values()),
            key=lambda shot: (shot.scene_id, shot.order),
        )

    def get_assets(self) -> list[Asset]:
        return [item.model_copy(deep=True) for item in self.assets.values()]

    def get_traces(self) -> list[TraceRecord]:
        return [item.model_copy(deep=True) for item in self.traces.values()]

    def list_traces_for_entity(self, entity_id: str) -> list[TraceRecord]:
        return [
            item.model_copy(deep=True)
            for item in self.traces.values()
            if item.entity_id == entity_id
        ]

    def list_traces_for_shot(self, shot_id: str) -> list[TraceRecord]:
        return [
            item.model_copy(deep=True)
            for item in self.traces.values()
            if item.shot_id == shot_id
        ]

    def snapshot(self) -> dict[str, list[dict]]:
        return {
            "entities": [item.model_dump(mode="json") for item in self.get_entities()],
            "shots": [item.model_dump(mode="json") for item in self.get_shots()],
            "assets": [item.model_dump(mode="json") for item in self.get_assets()],
            "traces": [item.model_dump(mode="json") for item in self.get_traces()],
        }

    def clear(self) -> None:
        self.entities.clear()
        self.shots.clear()
        self.assets.clear()
        self.traces.clear()
