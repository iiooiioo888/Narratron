"""Plug-in Bus 契約：PluginContext / PluginResult / TriggerPhase。"""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from narratron.hardware.pools import SceneComplexity
from narratron.vault.schema import Entity, TraceRecord


class TriggerPhase(str, Enum):
    """生成前 / 生成後。"""

    PRE = "pre"
    POST = "post"


class PluginContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: str
    phase: TriggerPhase
    prompt: str = ""
    entities: list[Entity] = Field(default_factory=list)
    traces: list[TraceRecord] = Field(default_factory=list)
    complexity: SceneComplexity = Field(default_factory=SceneComplexity)
    media_uri: str | None = None


class PluginResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool = True
    prompt_delta: str | None = None
    flags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Plugin(Protocol):
    plugin_id: str
    code: str
    name_zh: str
    triggers: tuple[TriggerPhase, ...]

    def run(self, context: PluginContext) -> PluginResult: ...
