"""壓縮護照內的生圖擴充欄位，避免把完整 API 回應巢狀寫回 current.charpass。"""

from __future__ import annotations

from typing import Any

IMAGE_GEN_BLOB_KEYS = frozenset(
    {
        "last_api_response",
        "last_full_response",
        "full_response",
        "raw_response",
        "manifest_candidate",
    }
)


def compact_image_gen_extensions(manifest: dict[str, Any] | None) -> dict[str, Any]:
    """就地移除 image_gen 內的大型回應副本，只保留路徑與年齡軸索引。"""
    data = manifest if isinstance(manifest, dict) else {}
    extensions = data.get("_extensions")
    if not isinstance(extensions, dict):
        return data
    image_gen = extensions.get("image_gen")
    if not isinstance(image_gen, dict):
        return data
    _compact_mapping(image_gen, depth=0)
    history = image_gen.get("history")
    if isinstance(history, list):
        cleaned: list[dict[str, Any]] = []
        for item in history:
            if not isinstance(item, dict):
                continue
            cleaned.append({key: value for key, value in item.items() if key not in IMAGE_GEN_BLOB_KEYS})
        image_gen["history"] = cleaned[-20:]
    return data


def _compact_mapping(payload: dict[str, Any], *, depth: int) -> None:
    for key in list(payload.keys()):
        if key in IMAGE_GEN_BLOB_KEYS:
            payload.pop(key, None)
            continue
        value = payload[key]
        if isinstance(value, dict):
            if depth >= 6:
                continue
            _compact_mapping(value, depth=depth + 1)
        elif isinstance(value, list) and depth < 4:
            for item in value:
                if isinstance(item, dict):
                    _compact_mapping(item, depth=depth + 1)
