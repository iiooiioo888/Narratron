"""FLUX / SDXL。綁定 Big / Mid / Alt Core。

Alpha Q1 僅允許把參考圖資產排入 IP-Adapter 微調佇列，禁止 generate()。
"""

from __future__ import annotations

from narratron.vault.schema import Asset
from narratron.vault.state_vault import StateVault


class Flux:
    def generate(self, prompt: str) -> str:
        raise NotImplementedError("Flux 模型呼叫待 Alpha Q3；本階段禁止 API")

    def queue_ip_adapter_finetune(self, vault: StateVault, assets: list[Asset]) -> Asset:
        return queue_ip_adapter_finetune(vault, assets)


def queue_ip_adapter_finetune(vault: StateVault, assets: list[Asset]) -> Asset:
    """寫入微調任務 metadata，不呼叫 GPU 或任何模型 API。"""

    refs = [item for item in assets if item.kind == "reference_image"]
    job = Asset(
        id="ip-adapter-finetune",
        kind="ip_adapter_finetune",
        uri="",
        metadata={
            "status": "queued",
            "backend": "IP-Adapter",
            "reference_ids": [item.id for item in refs],
            "note": "僅排隊，不呼叫 GPU / 模型 API",
        },
    )
    vault.upsert_assets([job])
    return job
