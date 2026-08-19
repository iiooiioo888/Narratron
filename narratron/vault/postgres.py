"""PostgreSQL + JSONB 後端。需 extra `infra`（psycopg）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from narratron.vault.ddl import SCHEMA_SQL
from narratron.vault.schema import Asset, Entity, EntityKind, Shot, TraceRecord


def _jsonb(value: dict[str, Any]) -> Any:
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _as_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


class PostgresStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self.ensure_schema()

    def _connect(self) -> Any:
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("PostgreSQL 後端需要 pip install -e \".[infra]\"") from exc
        return psycopg.connect(self._dsn, autocommit=True)

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(SCHEMA_SQL)

    def upsert_entities(self, entities: list[Entity]) -> None:
        sql = """
            INSERT INTO entities (id, kind, name, payload, created_at)
            VALUES (%s, %s, %s, %s, COALESCE(%s, now()))
            ON CONFLICT (id) DO UPDATE SET
                kind = EXCLUDED.kind,
                name = EXCLUDED.name,
                payload = EXCLUDED.payload
        """
        with self._connect() as conn:
            for item in entities:
                conn.execute(
                    sql,
                    (
                        item.id,
                        item.kind.value,
                        item.name,
                        _jsonb(item.payload),
                        item.created_at,
                    ),
                )

    def upsert_shots(self, shots: list[Shot]) -> None:
        sql = """
            INSERT INTO shots (id, scene_id, "order", camera_language, duration_ms, payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                scene_id = EXCLUDED.scene_id,
                "order" = EXCLUDED."order",
                camera_language = EXCLUDED.camera_language,
                duration_ms = EXCLUDED.duration_ms,
                payload = EXCLUDED.payload
        """
        with self._connect() as conn:
            for item in shots:
                conn.execute(
                    sql,
                    (
                        item.id,
                        item.scene_id,
                        item.order,
                        item.camera_language,
                        item.duration_ms,
                        _jsonb(item.payload),
                    ),
                )

    def upsert_assets(self, assets: list[Asset]) -> None:
        sql = """
            INSERT INTO assets (id, entity_id, kind, uri, metadata)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                entity_id = EXCLUDED.entity_id,
                kind = EXCLUDED.kind,
                uri = EXCLUDED.uri,
                metadata = EXCLUDED.metadata
        """
        with self._connect() as conn:
            for item in assets:
                conn.execute(
                    sql,
                    (item.id, item.entity_id, item.kind, item.uri, _jsonb(item.metadata)),
                )

    def append_traces(self, records: list[TraceRecord]) -> None:
        sql = """
            INSERT INTO trace_log (id, entity_id, shot_id, happened_at, cause, effect, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                entity_id = EXCLUDED.entity_id,
                shot_id = EXCLUDED.shot_id,
                happened_at = EXCLUDED.happened_at,
                cause = EXCLUDED.cause,
                effect = EXCLUDED.effect,
                payload = EXCLUDED.payload
        """
        with self._connect() as conn:
            for item in records:
                conn.execute(
                    sql,
                    (
                        item.id,
                        item.entity_id,
                        item.shot_id,
                        item.happened_at,
                        item.cause,
                        item.effect,
                        _jsonb(item.payload),
                    ),
                )

    def get_entities(self) -> list[Entity]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, kind, name, payload, created_at FROM entities ORDER BY created_at, id"
            ).fetchall()
        return [self._row_to_entity(row) for row in rows]

    def get_entity(self, entity_id: str) -> Entity | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, kind, name, payload, created_at FROM entities WHERE id = %s",
                (entity_id,),
            ).fetchone()
        return self._row_to_entity(row) if row is not None else None

    def delete_entity(self, entity_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM entities WHERE id = %s", (entity_id,))

    @staticmethod
    def _row_to_entity(row: Any) -> Entity:
        return Entity(
            id=row[0],
            kind=EntityKind(row[1]),
            name=row[2],
            payload=dict(row[3] or {}),
            created_at=_as_datetime(row[4]),
        )

    def get_shots(self) -> list[Shot]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, scene_id, "order", camera_language, duration_ms, payload
                FROM shots
                ORDER BY scene_id, "order"
                """
            ).fetchall()
        return [
            Shot(
                id=row[0],
                scene_id=row[1],
                order=row[2],
                camera_language=row[3],
                duration_ms=row[4],
                payload=dict(row[5] or {}),
            )
            for row in rows
        ]

    def get_assets(self) -> list[Asset]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, entity_id, kind, uri, metadata FROM assets ORDER BY id"
            ).fetchall()
        return [
            Asset(
                id=row[0],
                entity_id=row[1],
                kind=row[2],
                uri=row[3],
                metadata=dict(row[4] or {}),
            )
            for row in rows
        ]

    def get_traces(self) -> list[TraceRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, entity_id, shot_id, happened_at, cause, effect, payload
                FROM trace_log
                ORDER BY happened_at NULLS LAST, id
                """
            ).fetchall()
        return [self._row_to_trace(row) for row in rows]

    def list_traces_for_entity(self, entity_id: str) -> list[TraceRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, entity_id, shot_id, happened_at, cause, effect, payload
                FROM trace_log
                WHERE entity_id = %s
                ORDER BY happened_at NULLS LAST, id
                """,
                (entity_id,),
            ).fetchall()
        return [self._row_to_trace(row) for row in rows]

    def list_traces_for_shot(self, shot_id: str) -> list[TraceRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, entity_id, shot_id, happened_at, cause, effect, payload
                FROM trace_log
                WHERE shot_id = %s
                ORDER BY happened_at NULLS LAST, id
                """,
                (shot_id,),
            ).fetchall()
        return [self._row_to_trace(row) for row in rows]

    @staticmethod
    def _row_to_trace(row: Any) -> TraceRecord:
        return TraceRecord(
            id=row[0],
            entity_id=row[1],
            shot_id=row[2],
            happened_at=_as_datetime(row[3]),
            cause=row[4] or "",
            effect=row[5] or "",
            payload=dict(row[6] or {}),
        )
