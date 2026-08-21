from __future__ import annotations

from datetime import datetime, timezone

from characteros.routers.admin import _normalized_task_payload, _task_item_from_dict
from characteros.services.branch_summary import strip_final_asset_path_from_branch


def test_task_item_sanitizes_final_asset_path_for_pending() -> None:
    """尚未生圖完成（無 images）的 pending 任務仍應剝除 final_asset_path。"""
    now = datetime.now(timezone.utc).isoformat()
    raw = {
        "id": 1,
        "core_id": 1,
        "character_name": "test",
        "variant_hash": "vh",
        "evolution_params": {},
        "status": "pending",
        "priority": 0,
        "retry_count": 0,
        "max_retries": 3,
        "created_at": now,
        "updated_at": now,
        "result_url": "/x",
        "result_metadata": {
            "review_status": "pending",
            "effective_status": "pending",
            "image_generation": {
                "review_status": "pending",
                "review": {"status": "pending"},
                "images": [
                    {"angle": "front", "asset_path": "staging/front.png", "final_asset_path": "assets/front.png"},
                ],
            },
        },
    }

    task = _task_item_from_dict(raw, "database")
    image_generation = task.result_metadata["image_generation"]
    assert task.review_status == "pending"
    assert "final_asset_path" not in image_generation["images"][0]
    assert raw["result_metadata"]["image_generation"]["images"][0]["final_asset_path"] == "assets/front.png"


def test_task_item_auto_accept_ready_generation() -> None:
    """ready 且已有生圖結果時，視同 accepted（自動入庫）。"""
    now = datetime.now(timezone.utc).isoformat()
    raw = {
        "id": 1,
        "core_id": 1,
        "character_name": "test",
        "variant_hash": "vh",
        "evolution_params": {},
        "status": "ready",
        "priority": 0,
        "retry_count": 0,
        "max_retries": 3,
        "created_at": now,
        "updated_at": now,
        "result_url": "/x",
        "result_metadata": {
            "review_status": "pending",
            "effective_status": "pending",
            "angles": ["front", "face_detail"],
            "image_count": 2,
            "thumbnail_asset_path": "staging/thumb.png",
            "face_detail_asset_path": "staging/face.png",
            "face_detail_count": 1,
            "representative_asset_path": "staging/face.png",
            "representative_angle": "face_detail",
            "image_generation": {
                "review_status": "pending",
                "review": {"status": "pending"},
                "images": [
                    {"angle": "front", "asset_path": "staging/front.png", "final_asset_path": "assets/front.png"},
                ],
            },
        },
    }

    task = _task_item_from_dict(raw, "database")
    assert task.review_status == "accepted"
    assert task.effective_status == "accepted"
    assert "final_asset_path" in task.result_metadata["image_generation"]["images"][0]


def test_task_item_keeps_final_asset_path_for_accepted() -> None:
    now = datetime.now(timezone.utc).isoformat()
    raw = {
        "id": 1,
        "core_id": 1,
        "character_name": "test",
        "variant_hash": "vh",
        "evolution_params": {},
        "status": "ready",
        "priority": 0,
        "retry_count": 0,
        "max_retries": 3,
        "created_at": now,
        "updated_at": now,
        "result_url": "/x",
        "result_metadata": {
            "review_status": "accepted",
            "effective_status": "accepted",
            "angles": ["front", "face_detail"],
            "image_count": 2,
            "thumbnail_asset_path": "assets/thumb.png",
            "face_detail_asset_path": "assets/face.png",
            "face_detail_count": 1,
            "representative_asset_path": "assets/face.png",
            "representative_angle": "face_detail",
            "image_generation": {
                "review_status": "accepted",
                "review": {"status": "accepted"},
                "images": [
                    {"angle": "front", "asset_path": "assets/front.png", "final_asset_path": "assets/front.png"},
                ],
                "images_by_angle": {"front": [{"asset_path": "assets/front.png", "final_asset_path": "assets/front.png"}]},
                "face_detail_images": [{"asset_path": "assets/face.png", "final_asset_path": "assets/face.png"}],
                "thumbnail_image": {"asset_path": "assets/thumb.png", "final_asset_path": "assets/thumb.png"},
            },
        },
    }

    task = _task_item_from_dict(raw, "database")
    image_generation = task.result_metadata["image_generation"]
    assert "final_asset_path" in image_generation["images"][0]


def test_task_item_sanitizes_final_asset_path_for_rejected() -> None:
    now = datetime.now(timezone.utc).isoformat()
    raw = {
        "id": 2,
        "core_id": 1,
        "character_name": "test",
        "variant_hash": "vh",
        "evolution_params": {},
        "status": "ready",
        "priority": 0,
        "retry_count": 0,
        "max_retries": 3,
        "created_at": now,
        "updated_at": now,
        "result_metadata": {
            "review_status": "rejected",
            "image_generation": {
                "review_status": "rejected",
                "images": [
                    {"angle": "front", "asset_path": "staging/front.png", "final_asset_path": "assets/front.png"},
                ],
            },
        },
    }

    task = _task_item_from_dict(raw, "local")
    image_generation = task.result_metadata["image_generation"]
    assert "final_asset_path" not in image_generation["images"][0]


def test_normalized_task_payload_matches_list_endpoint_shape() -> None:
    now = datetime.now(timezone.utc).isoformat()
    raw = {
        "id": 3,
        "core_id": 1,
        "character_name": "test",
        "variant_hash": "vh",
        "evolution_params": {},
        "status": "ready",
        "priority": 0,
        "retry_count": 0,
        "max_retries": 3,
        "created_at": now,
        "updated_at": now,
        "review_status": "pending",
        "result_metadata": {
            "review_status": "pending",
            "purpose": "identity",
            "angles": ["face_detail", "front"],
            "face_detail_count": 1,
            "has_face_detail": True,
            "representative_angle": "face_detail",
            "representative_asset_path": "staging/face.png",
            "face_detail_asset_path": "staging/face.png",
            "thumbnail_asset_path": "staging/face.png",
            "image_generation": {
                "review_status": "pending",
                "purpose": "identity",
                "images": [
                    {"angle": "front", "asset_path": "staging/front.png", "final_asset_path": "assets/front.png"},
                ],
            },
        },
    }

    payload = _normalized_task_payload(raw, "database")
    assert payload["purpose"] == "identity"
    assert payload["face_detail_count"] == 1
    assert payload["representative_angle"] == "face_detail"
    assert payload["review_status"] == "accepted"
    assert payload["effective_status"] == "accepted"
    assert "final_asset_path" in payload["result_metadata"]["image_generation"]["images"][0]


def test_task_item_redacts_api_key_from_evolution_params() -> None:
    now = datetime.now(timezone.utc).isoformat()
    raw = {
        "id": 7,
        "core_id": 1,
        "character_name": "test",
        "variant_hash": "vh",
        "evolution_params": {
            "_image_request": {
                "purpose": "identity",
                "api_key": "sk-secret-should-not-leak",
            }
        },
        "status": "pending",
        "priority": 0,
        "retry_count": 0,
        "max_retries": 3,
        "created_at": now,
        "updated_at": now,
        "result_metadata": {},
    }

    item = _task_item_from_dict(raw, "local")
    image_request = item.evolution_params["_image_request"]
    assert "api_key" not in image_request
    assert image_request["has_api_key"] is True
    assert raw["evolution_params"]["_image_request"]["api_key"] == "sk-secret-should-not-leak"


def test_mutation_payload_sanitizes_pending_like_process_endpoint() -> None:
    """process/accept/reject 回傳與 list 端點一致；ready 且有結果時視同 accepted。"""
    now = datetime.now(timezone.utc).isoformat()
    raw = {
        "id": 4,
        "core_id": 1,
        "character_name": "test",
        "variant_hash": "vh",
        "evolution_params": {},
        "status": "ready",
        "priority": 0,
        "retry_count": 0,
        "max_retries": 3,
        "created_at": now,
        "updated_at": now,
        "result_metadata": {
            "review_status": "pending",
            "image_generation": {
                "review_status": "pending",
                "images": [
                    {"angle": "front", "asset_path": "staging/front.png", "final_asset_path": "assets/front.png"},
                ],
            },
        },
    }

    for storage_mode in ("local", "database"):
        payload = _normalized_task_payload(raw, storage_mode)
        images = payload["result_metadata"]["image_generation"]["images"]
        assert images[0]["asset_path"] == "staging/front.png"
        assert "final_asset_path" in images[0]
        assert payload["review_status"] == "accepted"


def test_mutation_task_payload_matches_list_normalization() -> None:
    """process/accept/reject 回傳應與 list 端點使用相同的 _task_item_from_dict 正規化。"""
    now = datetime.now(timezone.utc).isoformat()
    raw = {
        "id": 9,
        "core_id": 1,
        "character_name": "test",
        "variant_hash": "vh",
        "evolution_params": {},
        "status": "ready",
        "priority": 0,
        "retry_count": 0,
        "max_retries": 3,
        "created_at": now,
        "updated_at": now,
        "result_url": "/x",
        "result_metadata": {
            "review_status": "pending",
            "image_generation": {
                "review_status": "pending",
                "images": [
                    {"angle": "front", "asset_path": "staging/front.png", "final_asset_path": "assets/front.png"},
                ],
            },
        },
    }

    listed = _task_item_from_dict(raw, "database").model_dump(mode="json")
    processed = _normalized_task_payload(raw, "database")
    assert processed == listed
    assert "final_asset_path" in processed["result_metadata"]["image_generation"]["images"][0]


def test_normalized_task_payload_sanitizes_pending_like_list_endpoint() -> None:
    now = datetime.now(timezone.utc).isoformat()
    raw = {
        "id": 2,
        "core_id": 1,
        "character_name": "test",
        "variant_hash": "vh",
        "evolution_params": {},
        "status": "ready",
        "priority": 0,
        "retry_count": 0,
        "max_retries": 3,
        "created_at": now,
        "updated_at": now,
        "result_url": "/x",
        "result_metadata": {
            "review_status": "pending",
            "image_generation": {
                "review_status": "pending",
                "images": [
                    {"angle": "front", "asset_path": "staging/front.png", "final_asset_path": "assets/front.png"},
                ],
            },
        },
    }

    payload = _normalized_task_payload(raw, "local")
    image_generation = payload["result_metadata"]["image_generation"]
    assert "final_asset_path" in image_generation["images"][0]
    assert payload["review_status"] == "accepted"
    assert payload["effective_status"] == "accepted"


def test_version_summary_branch_strips_final_asset_path_for_pending() -> None:
    branch = {
        "review_status": "pending",
        "images_by_angle": {
            "front": [
                {"asset_path": "staging/front.png", "final_asset_path": "assets/front.png"},
            ],
        },
        "response": {
            "images_by_angle": {
                "face_detail": [
                    {"asset_path": "staging/face.png", "final_asset_path": "assets/face.png"},
                ],
            },
        },
    }
    strip_final_asset_path_from_branch(branch)
    assert "final_asset_path" not in branch["images_by_angle"]["front"][0]
    assert "final_asset_path" not in branch["response"]["images_by_angle"]["face_detail"][0]


def test_task_item_sanitize_does_not_mutate_source_metadata() -> None:
    now = datetime.now(timezone.utc).isoformat()
    raw = {
        "id": 11,
        "core_id": 1,
        "character_name": "test",
        "variant_hash": "vh",
        "evolution_params": {},
        "status": "ready",
        "priority": 0,
        "retry_count": 0,
        "max_retries": 3,
        "created_at": now,
        "updated_at": now,
        "result_metadata": {
            "review_status": "pending",
            "image_generation": {
                "review_status": "pending",
                "images": [
                    {"angle": "front", "asset_path": "staging/front.png", "final_asset_path": "assets/front.png"},
                ],
            },
        },
    }

    payload = _task_item_from_dict(raw, "database")
    assert "final_asset_path" in payload.result_metadata["image_generation"]["images"][0]
    assert payload.review_status == "accepted"
    assert raw["result_metadata"]["image_generation"]["images"][0]["final_asset_path"] == "assets/front.png"


def test_version_summary_branch_strip_does_not_mutate_shared_nested_source() -> None:
    shared_image = {"asset_path": "staging/front.png", "final_asset_path": "assets/front.png"}
    branch = {
        "review_status": "pending",
        "images_by_angle": {"front": [shared_image]},
        "response": {"images": [shared_image]},
    }
    strip_final_asset_path_from_branch(branch)
    assert "final_asset_path" not in branch["images_by_angle"]["front"][0]
    assert shared_image["final_asset_path"] == "assets/front.png"


def test_version_summary_branch_keeps_final_asset_path_for_accepted() -> None:
    branch = {
        "review_status": "accepted",
        "images_by_angle": {
            "front": [
                {"asset_path": "assets/front.png", "final_asset_path": "assets/front.png"},
            ],
        },
    }
    strip_final_asset_path_from_branch(branch)
    assert "final_asset_path" in branch["images_by_angle"]["front"][0]

