"""本機 charpass 後備儲存測試。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def test_local_queue_image_task_requires_acceptance_before_manifest_update(local_root: Path) -> None:
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
    assert review["status"] == "pending"
    assert processed["result_url"].startswith(f"/api/v1/characters/{core_id}/assets/causal/review/")
    assert processed["result_metadata"]["thumbnail_asset_path"].startswith("causal/review/identity/")
    assert processed["result_metadata"]["image_generation"]["thumbnail_asset_path"].startswith("causal/review/identity/")

    manifest_before = service.get_character_by_id(core_id).profile.manifest
    identity_before = manifest_before.get("_identity", {})
    assert not identity_before.get("ref_images")

    accepted = queue.review_task(int(task["id"]), accepted=True, character_service=service)
    assert accepted["result_metadata"]["image_generation"]["review"]["status"] == "accepted"
    assert accepted["result_metadata"]["review_status"] == "accepted"
    assert accepted["result_metadata"]["thumbnail_asset_path"].startswith("assets/identity/")
    assert accepted["result_metadata"]["image_generation"]["thumbnail_asset_path"].startswith("assets/identity/")

    manifest_after = service.get_character_by_id(core_id).profile.manifest
    assert manifest_after["_identity"]["ref_images"]


def test_local_queue_reject_keeps_manifest_unpublished(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    core_id = service.list_characters()["items"][0].id
    queue = LocalQueueManager(local_root)

    task, _is_new = queue.request_variant_generation(
        core_id=core_id,
        evolution_params={
            "_queue_nonce": "img-reject",
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
    staged_asset = processed["result_metadata"]["image_generation"]["images"][0]["asset_path"]
    rejected = queue.review_task(int(task["id"]), accepted=False, character_service=service)
    assert rejected["result_metadata"]["review_status"] == "rejected"
    assert rejected["result_metadata"]["image_generation"]["review"]["status"] == "rejected"
    assert rejected["result_url"] == processed["result_url"]

    manifest_after = service.get_character_by_id(core_id).profile.manifest
    assert not manifest_after.get("_identity", {}).get("ref_images")
    assert staged_asset.startswith("causal/review/identity/")
    assert not any(
        str(item.get("asset_path") or "").startswith("assets/identity/")
        for item in rejected["result_metadata"]["image_generation"]["images"]
    )


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
    assert image_branches[0]["status"] == "pending"
    assert image_branches[0]["review_status"] == "pending"
    assert image_branches[0]["effective_status"] == "pending"
    assert image_branches[0]["has_face_detail"] is False
    assert image_branches[0]["purpose_summary"] == "identity"
    assert image_branches[0]["angles_summary"] == "front"
    assert "pending" in image_branches[0]["summary"]
    assert image_branches[0]["thumbnail_asset_path"].startswith("causal/review/identity/")
    assert image_branches[0]["sort_key"].startswith("2:")
    assert image_branches[0]["sort_order"] == 0
    assert image_branches[0]["result_url"].startswith(f"/api/v1/characters/{core_id}/assets/causal/review/")


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
    assert branch["result_url"].endswith("ref_face_face_detail_001.png")
    assert branch["angles"][0] == "face_detail"
    assert branch["sort_key"].startswith("1:")


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
