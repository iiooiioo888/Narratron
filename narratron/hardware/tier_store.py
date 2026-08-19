"""Tier Store —— 分層儲存：熱 NVMe / 溫 SATA / 冷 HDD·S3。"""

from __future__ import annotations

from enum import Enum


class StorageTier(str, Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class TierStore:
    """Zstandard 壓縮策略待實作。"""

    def put(self, key: str, data: bytes, tier: StorageTier = StorageTier.HOT) -> None:
        raise NotImplementedError("Tier Store 待 Alpha")

    def get(self, key: str) -> bytes:
        raise NotImplementedError("Tier Store 待 Alpha")
