"""CharacterOS 變體指紋（variant_hash）計算，確保冪等。"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


# 僅供佇列追蹤，不得進入快取指紋。
_EPHEMERAL_KEYS = {
    "_queue_nonce",
    "_image_request",
    "provider",
    "model",
    "base_url",
    "api_key",
    "pipeline_id",
    "step_index",
    "total_steps",
    "depends_on",
    "asset_dir",
    "filename_prefix",
    "n",
    "multi_angle",
    "persist",
    "entity_id",
    "auto_accept",
}

_EMPTY = (None, "", [], {})

# 對外 API 用短名，快取指紋統一成 canonical 鍵。
_PARAM_ALIASES = {
    "age": "age_override",
    "emotion": "emotion_state",
    "scene": "scene_context",
    "injury": "injury_level",
}


def normalize_params(params: Dict[str, Any]) -> str:
    """
    標準化參數：排序鍵值、移除 null、轉換為一致格式
    確保相同的參數組合產生相同的 hash
    """
    normalized = json.loads(json.dumps(params))

    def sort_dict(d):
        if isinstance(d, dict):
            return {k: sort_dict(v) for k, v in sorted(d.items())}
        if isinstance(d, list):
            return [sort_dict(item) for item in d]
        return d

    sorted_params = sort_dict(normalized)
    return json.dumps(sorted_params, separators=(",", ":"), sort_keys=True)


def _fold_param_aliases(raw: Dict[str, Any]) -> Dict[str, Any]:
    """把 age/emotion/scene/injury 短名折成 canonical 鍵；正式鍵優先。"""
    folded: Dict[str, Any] = {}
    for key, value in raw.items():
        if key in _EPHEMERAL_KEYS or value in _EMPTY:
            continue
        dest = _PARAM_ALIASES.get(key, key)
        if dest in folded and key in _PARAM_ALIASES:
            continue
        folded[dest] = value
    return folded


def canonical_evolution_params(params: Dict[str, Any] | None) -> Dict[str, Any]:
    """抽出會改變外觀的語意參數，供 variant_hash 與快取查找使用。

    年齡軸的 pipeline_id / 佇列 nonce / provider 設定不參與指紋，
    因此「80 歲林默面部」不論來自按需請求或區間補齊，都能命中同一筆 character_variants。
    不同 emotion／scene／weather／injury 組合必須得到不同 hash。
    """
    raw = dict(params or {})
    image_request = raw.get("_image_request")
    canonical = _fold_param_aliases(raw)

    if isinstance(image_request, dict):
        purpose = str(image_request.get("purpose") or image_request.get("phase") or "").strip()
        if purpose and "purpose" not in canonical:
            canonical["purpose"] = purpose
        age = image_request.get("age")
        if age not in (None, "") and "age_override" not in canonical:
            try:
                canonical["age_override"] = int(age)
            except (TypeError, ValueError):
                pass
        user_extra = str(image_request.get("user_extra") or "").strip()
        if user_extra and "user_extra" not in canonical:
            canonical["user_extra"] = user_extra
        overlay = _fold_param_aliases(
            {key: image_request.get(key) for key in ("emotion", "scene", "weather", "injury", "emotion_state", "scene_context")}
        )
        for dest, value in overlay.items():
            if dest not in canonical:
                canonical[dest] = value

    return canonical


def manifest_fingerprint(manifest_content: Dict[str, Any] | None) -> str:
    """Profile manifest 內容指紋；版本變更或內容變更都會讓舊變體失效。"""
    if not manifest_content:
        return ""
    manifest_str = json.dumps(manifest_content, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(manifest_str.encode("utf-8")).hexdigest()[:16]


def compute_variant_hash(
    core_id: int,
    profile_version: int,
    evolution_params: Dict[str, Any],
    manifest_content: Dict[str, Any] | None = None,
) -> str:
    """
    計算變體指紋

    Args:
        core_id: 角色核心 ID
        profile_version: Profile 版本號
        evolution_params: 演化參數字典
        manifest_content: Profile manifest 內容（可選，用於內容感知的冪等性）

    Returns:
        SHA256 hash (64 characters)
    """
    hash_input = {
        "core_id": core_id,
        "profile_version": int(profile_version or 1),
        "manifest_hash": manifest_fingerprint(manifest_content),
        "evolution_params": canonical_evolution_params(evolution_params),
    }
    normalized = normalize_params(hash_input)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def verify_hash_match(
    core_id: int,
    profile_version: int,
    evolution_params: Dict[str, Any],
    expected_hash: str,
    manifest_content: Dict[str, Any] | None = None,
) -> bool:
    """驗證給定的 hash 是否匹配。"""
    computed = compute_variant_hash(core_id, profile_version, evolution_params, manifest_content)
    return computed == expected_hash


if __name__ == "__main__":
    params1 = {"age": 80, "emotion": "angry"}
    params2 = {"emotion": "angry", "age": 80}
    params3 = {"age": 80, "emotion": "happy"}

    hash1 = compute_variant_hash(1, 1, params1)
    hash2 = compute_variant_hash(1, 1, params2)
    hash3 = compute_variant_hash(1, 1, params3)

    print(f"Hash 1: {hash1}")
    print(f"Hash 2: {hash2}")
    print(f"Hash 3: {hash3}")

    assert hash1 == hash2, "相同參數應產生相同 hash"
    assert hash1 != hash3, "不同參數應產生不同 hash"

    nonce_a = {"age_override": 80, "_queue_nonce": "pipe-a", "_image_request": {"purpose": "face_detail", "age": 80, "pipeline_id": "a"}}
    nonce_b = {"age_override": 80, "_queue_nonce": "pipe-b", "_image_request": {"purpose": "face_detail", "age": 80, "pipeline_id": "b"}}
    assert compute_variant_hash(1, 1, nonce_a) == compute_variant_hash(1, 1, nonce_b)
    assert compute_variant_hash(1, 1, nonce_a) != compute_variant_hash(1, 2, nonce_a)

    print("✓ All hash tests passed!")
