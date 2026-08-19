"""
Narratron CharacterOS - Hash Utility
計算變體指紋（variant_hash）以確保冪等性
"""

import hashlib
import json
from typing import Dict, Any


def normalize_params(params: Dict[str, Any]) -> str:
    """
    標準化參數：排序鍵值、移除 null、轉換為一致格式
    確保相同的參數組合產生相同的 hash
    """
    # 深度拷貝以避免修改原始數據
    normalized = json.loads(json.dumps(params))
    
    # 遞迴處理嵌套字典
    def sort_dict(d):
        if isinstance(d, dict):
            return {k: sort_dict(v) for k, v in sorted(d.items())}
        elif isinstance(d, list):
            return [sort_dict(item) for item in d]
        else:
            return d
    
    sorted_params = sort_dict(normalized)
    
    # 轉換為 JSON 字串（compact 格式）
    return json.dumps(sorted_params, separators=(',', ':'), sort_keys=True)


def compute_variant_hash(
    core_id: int,
    profile_version: int,
    evolution_params: Dict[str, Any]
) -> str:
    """
    計算變體指紋
    
    Args:
        core_id: 角色核心 ID
        profile_version: Profile 版本號
        evolution_params: 演化參數字典
    
    Returns:
        SHA256 hash (64 characters)
    """
    # 組建指紋輸入
    hash_input = {
        "core_id": core_id,
        "profile_version": profile_version,
        "evolution_params": evolution_params
    }
    
    # 標準化並計算 hash
    normalized = normalize_params(hash_input)
    hash_bytes = normalized.encode('utf-8')
    hash_hex = hashlib.sha256(hash_bytes).hexdigest()
    
    return hash_hex


def verify_hash_match(
    core_id: int,
    profile_version: int,
    evolution_params: Dict[str, Any],
    expected_hash: str
) -> bool:
    """
    驗證給定的 hash 是否匹配
    
    Returns:
        True if match, False otherwise
    """
    computed = compute_variant_hash(core_id, profile_version, evolution_params)
    return computed == expected_hash


# 測試用
if __name__ == "__main__":
    # 測試用例
    params1 = {"age": 80, "emotion": "angry"}
    params2 = {"emotion": "angry", "age": 80}  # 順序不同但內容相同
    params3 = {"age": 80, "emotion": "happy"}  # 內容不同
    
    hash1 = compute_variant_hash(1, 1, params1)
    hash2 = compute_variant_hash(1, 1, params2)
    hash3 = compute_variant_hash(1, 1, params3)
    
    print(f"Hash 1: {hash1}")
    print(f"Hash 2: {hash2}")
    print(f"Hash 3: {hash3}")
    
    assert hash1 == hash2, "相同參數應產生相同 hash"
    assert hash1 != hash3, "不同參數應產生不同 hash"
    
    print("✓ All hash tests passed!")
