"""LangGraph Agent State：五智能體共用資料流。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from narratron.hardware.pools import HardwarePool
from narratron.vault.schema import Asset, Entity, Shot, TraceRecord


class AgentState(BaseModel):
    """Parser → Director → Keeper → Runner → Muxer。"""

    model_config = ConfigDict(extra="forbid")

    script: str = ""
    entities: list[Entity] = Field(default_factory=list)
    shots: list[Shot] = Field(default_factory=list)
    traces: list[TraceRecord] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    prompt: str = ""
    selected_pool: HardwarePool = HardwarePool.L1
    media_uris: list[str] = Field(default_factory=list)
    mux_uri: str | None = None
    bootstrap: dict[str, Any] | None = None
