"""CharacterOS 變體處理器：把 queue task 轉成可用的演化結果。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from characteros.services.evolution import EvolutionEngine


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sanitize_evolution_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """移除僅供佇列追蹤的暫時欄位，避免污染實際演化結果。"""
    raw = dict(params or {})
    raw.pop("_queue_nonce", None)
    raw.pop("_image_request", None)
    return raw


def extract_image_request(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """取出附掛在佇列上的生圖請求設定。"""
    raw = dict(params or {})
    image_request = raw.get("_image_request")
    if not isinstance(image_request, dict):
        return None
    return dict(image_request)


def evolve_manifest(
    base_manifest: dict[str, Any] | None,
    evolution_params: dict[str, Any] | None,
) -> dict[str, Any]:
    """根據演化參數產生新的 manifest 快照。"""
    manifest = dict(base_manifest or {})
    params = sanitize_evolution_params(evolution_params)
    evolved = EvolutionEngine().apply_evolution(manifest, params)

    meta = evolved.setdefault("_meta", {})
    meta["updated_at"] = utcnow_iso()
    meta.setdefault("mode", "full")

    causal = evolved.setdefault("_causal", {})
    log = causal.setdefault("evolution_log", [])
    if isinstance(log, list):
        log.append(
            {
                "type": "queue_variant_processed",
                "created_at": utcnow_iso(),
                "params": params,
            }
        )
    return evolved
