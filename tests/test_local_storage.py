"""本機 charpass 後備儲存測試。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from characteros.routers.admin import _task_item_from_dict
from characteros.storage.local_characters import LocalCharacterService
from characteros.storage.local_queue import LocalQueueManager
from characteros.models.schema import CharacterEditorUpdateRequest


@pytest.fixture()
def local_root(tmp_path: Path) -> Path:
    root = tmp_path / "charpasses"
    entity_dir = root / "character-test"
    entity_dir.mkdir(parents=True)
    manifest = {
        "schema": "https://narratron.dev/schemas/charpass/v1.json",
        "_meta": {"character_name": "測試角色", "tags": ["demo"]},
        "_identity": {"name": "測試角色", "gender_spectrum": 0.4, "age_appearance": "30"},
        "_style": {"character_style": {"visual": {"medium": "cinematic"}}},
    }
    (entity_dir / "current.charpass").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return root


def test_local_store_lists_and_loads_editor(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    listed = service.list_characters()
    assert listed["total"] == 1
    core = listed["items"][0]
    assert core.name == "測試角色"
    assert core.id == 1

    editor = service.get_editor_payload(core.id)
    assert editor.core.name == "測試角色"
    assert editor.profile.manifest.get("_identity", {}).get("name") == "測試角色"


def test_list_characters_prefers_existing_face_asset_over_missing_thumb(tmp_path: Path) -> None:
    root = tmp_path / "charpasses"
    entity = root / "character-卡爾"
    face_dir = entity / "assets" / "face_detail"
    face_dir.mkdir(parents=True)
    face_path = face_dir / "ref_face_detail_age_001_001.png"
    face_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    manifest = {
        "schema": "https://narratron.dev/schemas/charpass/v1.json",
        "_meta": {"character_name": "卡爾", "thumbnail": "thumb/thumb_256.png"},
        "_identity": {"name": "卡爾", "ref_images": []},
    }
    (entity / "current.charpass").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    service = LocalCharacterService(root)
    core = service.list_characters()["items"][0]
    assert core.metadata["face_detail_asset_path"] == "assets/face_detail/ref_face_detail_age_001_001.png"
    assert core.metadata["thumbnail_asset_path"] == "assets/face_detail/ref_face_detail_age_001_001.png"
    assert not str(core.metadata.get("thumbnail") or "").endswith("thumb_256.png")


def test_local_store_saves_editor_back_to_charpass(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    core_id = service.list_characters()["items"][0].id

    updated = service.update_character_editor(
        core_id,
        CharacterEditorUpdateRequest(
            name="測試角色二",
            base_age=31,
            gender_spectrum=0.5,
            tags=["demo", "local"],
            metadata={"note": "offline"},
            identity_anchor={"species": "human"},
            manifest={"_style": {"character_style": {"art_prompt": {"positive": "test"}}}},
        ),
    )
    assert updated.core.name == "測試角色二"

    raw = json.loads((local_root / "character-test" / "current.charpass").read_text(encoding="utf-8"))
    assert raw["_identity"]["name"] == "測試角色二"
    assert raw["_meta"]["tags"] == ["demo", "local"]


def test_ensure_character_creates_then_returns_existing(tmp_path: Path) -> None:
    service = LocalCharacterService(tmp_path)
    created, is_new = service.ensure_character("艾拉", notes="繃帶纏繞右臂")
    assert is_new is True
    assert created.name == "艾拉"
    assert created.base_age == 25
    assert (tmp_path / "character-艾拉" / "current.charpass").is_file()

    again, is_new_again = service.ensure_character("艾拉")
    assert is_new_again is False
    assert again.id == created.id
    assert service.list_characters()["total"] == 1


def test_ensure_character_api_and_sync(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from characteros.deps import get_character_backend
    from characteros.main import app

    service = LocalCharacterService(tmp_path)
    app.dependency_overrides[get_character_backend] = lambda: service
    try:
        client = TestClient(app)
        created = client.post("/api/v1/characters", json={"name": "卡爾"})
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["created"] is True
        assert body["name"] == "卡爾"

        again = client.post("/api/v1/characters", json={"name": "卡爾"})
        assert again.status_code == 200, again.text
        assert again.json()["created"] is False
        assert again.json()["id"] == body["id"]

        synced = client.post(
            "/api/v1/characters/sync-from-script",
            json={"names": ["卡爾", "艾拉", "卡爾", ""]},
        )
        assert synced.status_code == 200, synced.text
        payload = synced.json()
        assert payload["created_count"] == 1
        assert payload["existing_count"] == 1
        assert {item["name"] for item in payload["items"]} == {"卡爾", "艾拉"}
    finally:
        app.dependency_overrides.clear()


def test_local_queue_processes_pending_task_into_variant_artifact(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    core_id = service.list_characters()["items"][0].id
    queue = LocalQueueManager(local_root)

    task, is_new = queue.request_variant_generation(
        core_id=core_id,
        evolution_params={"age_override": 42, "emotion_state": "happy", "_queue_nonce": "demo"},
        character_name="測試角色",
    )
    assert is_new is True
    assert task["status"] == "pending"

    processed = queue.process_task(int(task["id"]), character_service=service)
    assert processed["status"] == "ready"
    assert processed["result_url"].endswith("/causal/variants/1/evolved-manifest.json")
    assert processed["result_metadata"]["evolved_manifest"]["_identity"]["name"] == "測試角色"
    assert (
        processed["result_metadata"]["evolved_manifest"]["_expression"]["base_emotion"]
        == "happy"
    )

    output = local_root / "character-test" / "causal" / "variants" / "1" / "evolved-manifest.json"
    assert output.is_file()


def test_local_queue_image_task_auto_publishes_manifest(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    core_id = service.list_characters()["items"][0].id
    queue = LocalQueueManager(local_root)

    task, _is_new = queue.request_variant_generation(
        core_id=core_id,
        evolution_params={
            "_queue_nonce": "img-review",
            "_image_request": {
                "purpose": "identity",
                "provider": "null",
                "multi_angle": False,
                "persist": True,
            },
        },
        character_name="測試角色",
    )

    processed = queue.process_task(int(task["id"]), character_service=service)
    review = processed["result_metadata"]["image_generation"]["review"]
    assert processed["status"] == "ready"
    assert review["status"] == "accepted"
    assert processed["result_metadata"]["image_generation"]["review_status"] == "accepted"
    assert processed["result_url"].startswith(f"/api/v1/characters/{core_id}/assets/assets/")
    assert processed["result_metadata"]["thumbnail_asset_path"].startswith("assets/identity/")
    assert processed["result_metadata"]["image_generation"]["thumbnail_asset_path"].startswith("assets/identity/")
    assets_dir = local_root / "character-test" / "assets"
    assert assets_dir.exists()
    assert any(assets_dir.rglob("*"))

    record = json.loads(
        (local_root / "character-test" / "causal" / "variants" / str(task["id"]) / "record.json").read_text(encoding="utf-8")
    )
    assert record["review_status"] == "accepted"
    assert record["thumbnail_asset_path"].startswith("assets/identity/")

    manifest_after = service.get_character_by_id(core_id).profile.manifest
    assert manifest_after["_identity"]["ref_images"]


def test_local_queue_process_publishes_without_manual_review(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    core_id = service.list_characters()["items"][0].id
    queue = LocalQueueManager(local_root)

    task, _is_new = queue.request_variant_generation(
        core_id=core_id,
        evolution_params={
            "_queue_nonce": "img-auto-accept",
            "_image_request": {
                "purpose": "identity",
                "provider": "null",
                "multi_angle": False,
                "persist": True,
            },
        },
        character_name="測試角色",
    )

    processed = queue.process_task(int(task["id"]), character_service=service)
    published_asset = processed["result_metadata"]["image_generation"]["images"][0]["asset_path"]
    assert processed["result_metadata"]["review_status"] == "accepted"
    assert processed["result_metadata"]["image_generation"]["review"]["status"] == "accepted"
    assert published_asset.startswith("assets/identity/")
    manifest_after = service.get_character_by_id(core_id).profile.manifest
    assert manifest_after.get("_identity", {}).get("ref_images")


def test_local_queue_prefers_face_detail_as_result_url_when_available(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    core_id = service.list_characters()["items"][0].id
    queue = LocalQueueManager(local_root)

    task, _is_new = queue.request_variant_generation(
        core_id=core_id,
        evolution_params={
            "_queue_nonce": "img-face-detail-url",
            "_image_request": {
                "purpose": "identity",
                "provider": "null",
                "multi_angle": True,
                "persist": True,
            },
        },
        character_name="測試角色",
    )

    processed = queue.process_task(int(task["id"]), character_service=service)
    assert processed["result_metadata"]["face_detail_asset_path"].startswith("assets/")
    assert processed["result_metadata"]["thumbnail_asset_path"].startswith("assets/")
    assert processed["result_metadata"]["representative_asset_path"] == processed["result_metadata"]["face_detail_asset_path"]
    assert processed["result_metadata"]["representative_angle"] == "face_detail"
    assert processed["result_metadata"]["has_face_detail"] is True
    assert processed["result_metadata"]["angles"][0] == "face_detail"
    assert "face_detail" in processed["result_url"]


def test_queue_task_payload_promotes_preview_summary_fields(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    core_id = service.list_characters()["items"][0].id
    queue = LocalQueueManager(local_root)

    task, _is_new = queue.request_variant_generation(
        core_id=core_id,
        evolution_params={
            "_queue_nonce": "img-task-summary",
            "_image_request": {
                "purpose": "identity",
                "provider": "null",
                "multi_angle": True,
                "persist": True,
            },
        },
        character_name="測試角色",
    )

    processed = queue.process_task(int(task["id"]), character_service=service)
    task_item = _task_item_from_dict(processed, "local")

    assert task_item.review_status == "accepted"
    assert task_item.effective_status == "accepted"
    assert task_item.purpose == "identity"
    assert task_item.has_face_detail is True
    assert task_item.face_detail_count >= 1
    assert task_item.representative_angle == "face_detail"
    assert task_item.representative_asset_path == task_item.face_detail_asset_path
    assert task_item.thumbnail_asset_path == task_item.face_detail_asset_path
    assert task_item.angles[0] == "face_detail"


def test_version_summary_includes_pending_image_review_branch(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    core_id = service.list_characters()["items"][0].id
    queue = LocalQueueManager(local_root)

    task, _is_new = queue.request_variant_generation(
        core_id=core_id,
        evolution_params={
            "_queue_nonce": "img-branch",
            "_image_request": {
                "purpose": "identity",
                "provider": "null",
                "multi_angle": False,
                "persist": True,
            },
        },
        character_name="測試角色",
    )

    queue.process_task(int(task["id"]), character_service=service)
    summary = service.get_version_summary(core_id)
    image_branches = [branch for branch in summary["branches"] if branch["kind"] == "image_gen"]

    assert image_branches
    assert image_branches[0]["purpose"] == "identity"
    assert image_branches[0]["status"] == "accepted"
    assert image_branches[0]["review_status"] == "accepted"
    assert image_branches[0]["effective_status"] == "accepted"
    assert image_branches[0]["has_face_detail"] is False
    assert image_branches[0]["purpose_summary"] == "identity"
    assert image_branches[0]["angles_summary"] == "front"
    assert image_branches[0]["summary_fields"]["purpose"] == "identity"
    assert image_branches[0]["summary_fields"]["angles"] == ["front"]
    assert image_branches[0]["thumbnail_asset_path"].startswith("assets/identity/")
    assert image_branches[0]["result_url"].startswith(f"/api/v1/characters/{core_id}/assets/assets/")
    images_by_angle = image_branches[0].get("images_by_angle") or {}
    for entries in images_by_angle.values():
        if not isinstance(entries, list):
            continue
        for item in entries:
            if isinstance(item, dict):
                assert "final_asset_path" not in item


def test_version_summary_includes_queue_variant_branch_metadata(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    core_id = service.list_characters()["items"][0].id
    queue = LocalQueueManager(local_root)

    task, _is_new = queue.request_variant_generation(
        core_id=core_id,
        evolution_params={
            "_queue_nonce": "img-variant-branch",
            "_image_request": {
                "purpose": "identity",
                "provider": "null",
                "multi_angle": True,
                "persist": True,
            },
        },
        character_name="測試角色",
    )

    processed = queue.process_task(int(task["id"]), character_service=service)
    summary = service.get_version_summary(core_id)
    branch = next(item for item in summary["branches"] if item["kind"] == "variant")

    assert branch["branch_id"] == str(processed["id"])
    assert branch["review_status"] == "accepted"
    assert branch["effective_status"] == "accepted"
    assert branch["has_face_detail"] is True
    assert branch["summary_fields"]["has_face_detail"] is True
    assert branch["summary_fields"]["purpose"] == "identity"
    assert branch["hero_asset_path"] == branch["face_detail_asset_path"]
    assert branch["representative_asset_path"] == branch["face_detail_asset_path"]
    assert branch["representative_angle"] == "face_detail"
    assert branch["provider"] == "null"
    assert branch["model"]
    assert branch["review"]["status"] == "accepted"
    assert branch["response"]["review"]["status"] == "accepted"
    assert branch["prompt"]
    assert branch["sort_priority"] == 1
    assert branch["result_url"].endswith(branch["face_detail_asset_path"])


def test_version_summary_prefers_face_detail_as_branch_thumbnail(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    core_id = service.list_characters()["items"][0].id
    entity_dir = local_root / "character-test"
    job_dir = entity_dir / "causal" / "image_gen" / "identity" / "job-face-detail"
    job_dir.mkdir(parents=True)
    (job_dir / "full-response.json").write_text(
        json.dumps({"review": {"status": "pending"}, "created_at": "2026-08-19T10:00:00Z"}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (job_dir / "record.json").write_text(
        json.dumps({"created_at": "2026-08-19T10:00:00Z"}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (job_dir / "images-index.json").write_text(
        json.dumps(
            {
                "images": [
                    {"filename": "ref_face_front_001.png", "angle": "front", "asset_path": "causal/review/identity/job-face-detail/ref_face_front_001.png"},
                    {"filename": "ref_face_face_detail_001.png", "angle": "face_detail", "asset_path": "causal/review/identity/job-face-detail/ref_face_face_detail_001.png"},
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = service.get_version_summary(core_id)
    branch = next(item for item in summary["branches"] if item["branch_id"] == "job-face-detail")
    assert branch["has_face_detail"] is True
    assert branch["face_detail_asset_path"].endswith("ref_face_face_detail_001.png")
    assert branch["thumbnail_asset_path"].endswith("ref_face_face_detail_001.png")
    assert branch["hero_asset_path"].endswith("ref_face_face_detail_001.png")
    assert branch["summary_fields"]["has_face_detail"] is True
    assert branch["summary_fields"]["face_detail_count"] == 1
    assert branch["result_url"].endswith("ref_face_face_detail_001.png")
    assert branch["angles"][0] == "face_detail"
    assert branch["sort_key"].startswith("1:")


def test_version_summary_image_branch_exposes_request_and_review_payloads(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    core_id = service.list_characters()["items"][0].id
    entity_dir = local_root / "character-test"
    job_dir = entity_dir / "causal" / "image_gen" / "identity" / "job-rich-payload"
    job_dir.mkdir(parents=True)
    (job_dir / "request.json").write_text(
        json.dumps({"prompt": "same character front view", "negative_prompt": "blur"}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (job_dir / "response.json").write_text(
        json.dumps({"images": [{"asset_path": "causal/review/identity/job-rich-payload/ref_face_front_001.png"}]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (job_dir / "full-response.json").write_text(
        json.dumps(
            {
                "provider": "wan",
                "model": "wan2.7-image-pro",
                "prompt": "same character front view",
                "negative_prompt": "blur",
                "review": {"status": "pending"},
                "created_at": "2026-08-19T10:00:00Z",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (job_dir / "record.json").write_text(
        json.dumps({"created_at": "2026-08-19T10:00:00Z"}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (job_dir / "images-index.json").write_text(
        json.dumps(
            {
                "images": [
                    {
                        "filename": "ref_face_front_001.png",
                        "angle": "front",
                        "asset_path": "causal/review/identity/job-rich-payload/ref_face_front_001.png",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = service.get_version_summary(core_id)
    branch = next(item for item in summary["branches"] if item["branch_id"] == "job-rich-payload")
    assert branch["provider"] == "wan"
    assert branch["model"] == "wan2.7-image-pro"
    assert branch["review"]["status"] == "pending"
    assert branch["request"]["prompt"] == "same character front view"
    assert branch["response"]["images"][0]["asset_path"].endswith("ref_face_front_001.png")
    assert branch["prompt"] == "same character front view"
    assert branch["negative_prompt"] == "blur"


def test_version_summary_orders_face_detail_branch_first_for_same_timestamp(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    core_id = service.list_characters()["items"][0].id
    entity_dir = local_root / "character-test"
    image_root = entity_dir / "causal" / "image_gen"
    shared_timestamp = "2026-08-19T10:00:00Z"

    identity_dir = image_root / "identity" / "job-identity"
    identity_dir.mkdir(parents=True)
    (identity_dir / "full-response.json").write_text(
        json.dumps({"review": {"status": "pending"}, "created_at": shared_timestamp}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (identity_dir / "record.json").write_text(
        json.dumps({"created_at": shared_timestamp}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (identity_dir / "images-index.json").write_text(
        json.dumps(
            {
                "images": [
                    {
                        "filename": "ref_face_front_001.png",
                        "angle": "front",
                        "asset_path": "causal/review/identity/job-identity/ref_face_front_001.png",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    face_detail_dir = image_root / "face_detail" / "job-face-detail-priority"
    face_detail_dir.mkdir(parents=True)
    (face_detail_dir / "full-response.json").write_text(
        json.dumps({"review": {"status": "pending"}, "created_at": shared_timestamp}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (face_detail_dir / "record.json").write_text(
        json.dumps({"created_at": shared_timestamp}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (face_detail_dir / "images-index.json").write_text(
        json.dumps(
            {
                "images": [
                    {
                        "filename": "ref_face_face_detail_001.png",
                        "angle": "face_detail",
                        "asset_path": "causal/review/face_detail/job-face-detail-priority/ref_face_face_detail_001.png",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = service.get_version_summary(core_id)
    image_branches = [branch for branch in summary["branches"] if branch["kind"] == "image_gen"]
    assert image_branches[0]["branch_id"] == "job-face-detail-priority"
    assert image_branches[0]["purpose"] == "face_detail"
    assert image_branches[0]["sort_key"].startswith("2:")
    assert image_branches[1]["branch_id"] == "job-identity"


def test_version_summary_queue_branch_falls_back_to_top_level_asset_fields(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    queue_data = {
        "next_id": 2,
        "tasks": [
            {
                "id": 1,
                "core_id": 1,
                "character_name": "測試角色",
                "profile_version": 1,
                "variant_hash": "fallback-branch",
                "evolution_params": {},
                "status": "ready",
                "priority": 0,
                "result_url": None,
                "result_metadata": {
                    "review_status": "pending",
                    "thumbnail_asset_path": "causal/review/identity/fallback/front.png",
                    "face_detail_asset_path": "causal/review/identity/fallback/face_detail.png",
                    "image_generation": {
                        "purpose": "identity",
                        "images": [],
                        "images_by_angle": {},
                    },
                },
                "error_message": None,
                "retry_count": 0,
                "max_retries": 3,
                "queue_wait_ms": 0,
                "generation_duration_ms": 0,
                "created_at": "2026-08-19T10:00:00Z",
                "updated_at": "2026-08-19T10:00:01Z",
            }
        ],
    }
    (local_root / ".characteros-queue.json").write_text(
        json.dumps(queue_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = service.get_version_summary(1)
    branch = next(item for item in summary["branches"] if item["kind"] == "variant")
    assert branch["face_detail_asset_path"] == "causal/review/identity/fallback/face_detail.png"
    assert branch["thumbnail_asset_path"] == "causal/review/identity/fallback/face_detail.png"
    assert branch["hero_asset_path"] == "causal/review/identity/fallback/face_detail.png"
    assert branch["angles"] == ["face_detail", "front"]
    assert branch["result_url"].endswith("causal/review/identity/fallback/face_detail.png")


def test_version_summary_infers_face_detail_from_review_payload_metadata(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    queue_data = {
        "next_id": 2,
        "tasks": [
            {
                "id": 1,
                "core_id": 1,
                "character_name": "測試角色",
                "profile_version": 1,
                "variant_hash": "inferred-face-detail",
                "evolution_params": {},
                "status": "ready",
                "priority": 0,
                "result_url": None,
                "result_metadata": {
                    "review_status": "pending",
                    "image_generation": {
                        "purpose": "identity",
                        "images": [
                            {
                                "filename": "generated_001.png",
                                "asset_path": "causal/review/identity/job-1/generated_001.png",
                                "final_asset_path": "assets/face_detail/generated_001.png",
                                "prompt": "[face_detail] same character facial close-up",
                            }
                        ],
                        "images_by_angle": {},
                    },
                },
                "error_message": None,
                "retry_count": 0,
                "max_retries": 3,
                "queue_wait_ms": 0,
                "generation_duration_ms": 0,
                "created_at": "2026-08-19T10:00:00Z",
                "updated_at": "2026-08-19T10:00:01Z",
            }
        ],
    }
    (local_root / ".characteros-queue.json").write_text(
        json.dumps(queue_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = service.get_version_summary(1)
    branch = next(item for item in summary["branches"] if item["kind"] == "variant")
    assert branch["has_face_detail"] is True
    assert branch["face_detail_count"] == 1
    assert branch["face_detail_asset_path"] == "causal/review/identity/job-1/generated_001.png"
    assert branch["thumbnail_asset_path"] == "causal/review/identity/job-1/generated_001.png"
    assert branch["hero_asset_path"] == "causal/review/identity/job-1/generated_001.png"
    assert branch["angles"] == ["face_detail"]
    assert branch["summary_fields"]["face_detail_count"] == 1


def test_local_store_save_charpass_and_version_summary(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    core_id = service.list_characters()["items"][0].id
    original = service.get_character_by_id(core_id).profile.manifest
    original["_extensions"] = {
        "image_gen": {
            "latest_by_purpose": {
                "identity": {
                    "job_id": "job-1",
                    "asset_paths": ["assets/identity/ref_face_front_001.png"],
                    "angles": ["front", "face_detail"],
                    "updated_at": "2026-08-19T07:47:52Z",
                }
            }
        }
    }

    saved = service.save_charpass(core_id, original)
    assert saved["_meta"]["entity_id"] == "character-test"

    summary = service.get_version_summary(core_id)
    assert summary["current_path"] == "current.charpass"
    assert any(item["name"] == "current.charpass" for item in summary["history"])
    branch = next(branch for branch in summary["branches"] if branch["label"] == "image_gen/identity")
    assert branch["review_status"] == "accepted"
    assert branch["thumbnail_asset_path"] == "assets/identity/ref_face_front_001.png"
    assert branch["sort_order"] == 0


def test_task_item_from_dict_parity_local_and_database() -> None:
    """同一 raw metadata 在 local / database storage_mode 下應產出相同頂層欄位。"""
    now = datetime.now(timezone.utc).isoformat()
    raw = {
        "id": 99,
        "core_id": 1,
        "character_name": "parity",
        "variant_hash": "vh-parity",
        "evolution_params": {"k": "v"},
        "status": "ready",
        "priority": 1,
        "retry_count": 0,
        "max_retries": 3,
        "created_at": now,
        "updated_at": now,
        "result_url": "/api/x",
        "result_metadata": {
            "review_status": "pending",
            "effective_status": "pending",
            "purpose": "identity",
            "angles": ["face_detail", "front"],
            "image_count": 2,
            "thumbnail_asset_path": "causal/review/identity/job/thumb.png",
            "face_detail_asset_path": "causal/review/identity/job/face.png",
            "face_detail_count": 1,
            "has_face_detail": True,
            "representative_asset_path": "causal/review/identity/job/face.png",
            "representative_angle": "face_detail",
            "image_generation": {
                "review_status": "pending",
                "purpose": "identity",
                "angles": ["front"],
                "face_detail_count": 0,
                "images": [
                    {
                        "angle": "face_detail",
                        "asset_path": "causal/review/identity/job/face.png",
                        "final_asset_path": "assets/identity/face.png",
                    }
                ],
            },
        },
    }

    local_item = _task_item_from_dict(raw, "local")
    database_item = _task_item_from_dict(raw, "database")

    assert local_item.model_dump() == database_item.model_dump()
    assert local_item.review_status == "accepted"
    assert local_item.effective_status == "accepted"
    assert local_item.purpose == "identity"
    assert local_item.face_detail_count == 1
    assert local_item.representative_angle == "face_detail"
    assert local_item.has_face_detail is True
    assert local_item.angles == ["face_detail", "front"]
    assert raw["result_metadata"]["image_generation"]["images"][0]["final_asset_path"] == "assets/identity/face.png"


def test_local_queue_reject_records_rejected_at(local_root: Path) -> None:
    """拒絕任務不得再呼叫未匯入的 utcnow_iso，且須寫入 rejected_at。"""
    service = LocalCharacterService(local_root)
    core_id = service.list_characters()["items"][0].id
    queue = LocalQueueManager(local_root)
    now = datetime.now(timezone.utc).isoformat()
    data = queue._load()
    data["next_id"] = 2
    data["tasks"] = [
        {
            "id": 1,
            "core_id": core_id,
            "character_name": "測試角色",
            "variant_hash": "vh-reject",
            "evolution_params": {},
            "status": "ready",
            "priority": 0,
            "result_url": None,
            "result_metadata": {
                "image_generation": {
                    "review": {"status": "pending"},
                    "images": [{"asset_path": "staging/front.png"}],
                }
            },
            "error_message": None,
            "retry_count": 0,
            "max_retries": 3,
            "created_at": now,
            "updated_at": now,
        }
    ]
    queue._save(data)

    rejected = queue.review_task(1, accepted=False, character_service=service)
    review = rejected["result_metadata"]["image_generation"]["review"]
    assert review["status"] == "rejected"
    assert review.get("rejected_at")
    assert queue.get_task_by_id(1)["result_metadata"]["image_generation"]["review"]["status"] == "rejected"


def test_reset_failed_tasks_persists_waiting(local_root: Path) -> None:
    """批次重設 failed 不得因中途 _load() 而丟掉狀態變更。"""
    service = LocalCharacterService(local_root)
    core_id = service.list_characters()["items"][0].id
    queue = LocalQueueManager(local_root)
    now = datetime.now(timezone.utc).isoformat()
    data = queue._load()
    data["next_id"] = 2
    data["tasks"] = [
        {
            "id": 1,
            "core_id": core_id,
            "character_name": "測試角色",
            "variant_hash": "vh-fail",
            "evolution_params": {},
            "status": "failed",
            "priority": 0,
            "result_metadata": {},
            "error_message": "boom",
            "retry_count": 1,
            "max_retries": 3,
            "created_at": now,
            "updated_at": now,
        }
    ]
    queue._save(data)

    reset = queue.reset_failed_tasks()
    assert len(reset) == 1
    assert reset[0]["status"] == "waiting"
    assert reset[0]["error_message"] is None
    persisted = queue.get_task_by_id(1)
    assert persisted is not None
    assert persisted["status"] == "waiting"
    assert persisted["error_message"] is None


def test_nested_enqueue_does_not_clobber_next_id(local_root: Path) -> None:
    """ensure_following / process_next 外層 _save 不得把 next_id 蓋回舊值造成重複 ID。"""
    service = LocalCharacterService(local_root)
    core_id = service.list_characters()["items"][0].id
    queue = LocalQueueManager(local_root)
    now = datetime.now(timezone.utc).isoformat()
    pipeline_id = "age-span-test-next-id"
    data = queue._load()
    data["next_id"] = 2
    data["tasks"] = [
        {
            "id": 1,
            "core_id": core_id,
            "character_name": "測試角色",
            "variant_hash": "vh-age-1",
            "evolution_params": {
                "age_override": 1,
                "_queue_nonce": f"{pipeline_id}-face_detail-age-001",
                "_image_request": {
                    "purpose": "face_detail",
                    "pipeline": "age_span",
                    "pipeline_id": pipeline_id,
                    "phase": "face_detail",
                    "age": 1,
                    "age_start": 1,
                    "age_end": 3,
                    "step_index": 0,
                    "total_steps": 6,
                    "depends_on": None,
                },
            },
            "status": "ready",
            "priority": 6,
            "result_url": "https://cdn.example/face-1.png",
            "result_metadata": {
                "image_generation": {
                    "images": [{"url": "https://cdn.example/face-1.png"}],
                    "review": {"status": "accepted"},
                }
            },
            "error_message": None,
            "retry_count": 0,
            "max_retries": 3,
            "created_at": now,
            "updated_at": now,
        }
    ]
    queue._save(data)

    created = queue.ensure_following_age_span_tasks(core_id=core_id)
    assert len(created) == 1
    persisted = queue._load()
    ids = [int(t["id"]) for t in persisted["tasks"]]
    assert len(ids) == len(set(ids)), f"duplicate task ids: {ids}"
    assert int(persisted["next_id"]) == max(ids) + 1
    assert any(
        (t.get("evolution_params") or {}).get("_image_request", {}).get("age") == 2
        for t in persisted["tasks"]
    )


def test_repair_task_ids_renumbers_duplicates(local_root: Path) -> None:
    queue = LocalQueueManager(local_root)
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "next_id": 2,
        "tasks": [
            {
                "id": 1,
                "core_id": 1,
                "variant_hash": "a",
                "evolution_params": {},
                "status": "ready",
                "priority": 0,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": 2,
                "core_id": 1,
                "variant_hash": "b",
                "evolution_params": {},
                "status": "ready",
                "priority": 0,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": 2,
                "core_id": 1,
                "variant_hash": "c",
                "evolution_params": {},
                "status": "pending",
                "priority": 0,
                "created_at": now,
                "updated_at": now,
            },
        ],
        "worker": {"paused": False},
    }
    queue._path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = queue.repair_task_ids()
    assert result["changed"] is True
    assert result["task_ids"] == [1, 2, 3]
    assert result["next_id"] == 4
    pending = next(t for t in queue._load()["tasks"] if t["status"] == "pending")
    assert pending["id"] == 3
    preferred = LocalQueueManager._select_task(
        [
            {"id": 2, "status": "ready", "variant_hash": "b"},
            {"id": 2, "status": "pending", "variant_hash": "c"},
        ],
        2,
    )
    assert preferred is not None
    assert preferred["status"] == "pending"


def test_asset_path_rejects_traversal(local_root: Path) -> None:
    from fastapi import HTTPException

    from characteros.routers.characters import _resolve_local_asset_path

    service = LocalCharacterService(local_root)
    with pytest.raises(HTTPException) as exc:
        _resolve_local_asset_path(1, "../.characteros-index.json", service)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        _resolve_local_asset_path(1, "/etc/passwd", service)
    assert exc.value.status_code == 404
