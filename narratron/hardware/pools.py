"""硬體算力池：L0 Big Core / L1 Mid Core / L2 Alt Core / L3 Light Core。"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class HardwarePool(str, Enum):
    """枚舉值為 Python 識別名；官方代號含空格見 naming.HARDWARE_POOLS。"""

    L0 = "BigCore"
    L1 = "MidCore"
    L2 = "AltCore"
    L3 = "LightCore"


POOL_ZH: dict[HardwarePool, str] = {
    HardwarePool.L0: "大核",
    HardwarePool.L1: "中核",
    HardwarePool.L2: "備核",
    HardwarePool.L3: "輕核",
}

POOL_CODE: dict[HardwarePool, str] = {
    HardwarePool.L0: "Big Core",
    HardwarePool.L1: "Mid Core",
    HardwarePool.L2: "Alt Core",
    HardwarePool.L3: "Light Core",
}


class SceneComplexity(BaseModel):
    """供 P7 Router 依人數 / 特效選池。"""

    model_config = ConfigDict(extra="forbid")

    character_count: int = Field(default=1, ge=0)
    vfx_level: int = Field(default=0, ge=0, le=10)


def select_pool(complexity: SceneComplexity) -> HardwarePool:
    """依複雜度選池。本階段固定回傳 Mid Core（L1）。"""

    _ = complexity
    return HardwarePool.L1
