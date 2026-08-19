"""State Vault schema 契約：表名與 JSONB 欄位凍結。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EntityKind(str, Enum):
    """角色 / 道具 / 場景。"""

    CHARACTER = "character"
    PROP = "prop"
    SCENE = "scene"


class Entity(BaseModel):
    """表 `entities`。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: EntityKind
    name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class Shot(BaseModel):
    """表 `shots`。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    scene_id: str
    order: int
    camera_language: str = ""
    duration_ms: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)


class TraceRecord(BaseModel):
    """表 `trace_log`（代號 Trace Log）。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    entity_id: str
    shot_id: str | None = None
    happened_at: datetime | None = None
    cause: str = ""
    effect: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class Asset(BaseModel):
    """表 `assets`（參考圖資產庫 metadata）。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    entity_id: str | None = None
    kind: str = "reference_image"
    uri: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


VAULT_TABLES: tuple[str, ...] = ("entities", "shots", "trace_log", "assets")
