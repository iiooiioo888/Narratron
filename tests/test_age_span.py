"""新人物年齡軸：1–80 歲連貫面部細緻圖，再接 T 型外觀圖。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from characteros.imaging.prompt import assemble_request
from characteros.services.age_span import (
    age_span_steps,
    build_age_span_evolution_params,
    collect_age_span_ref_uris,
    initial_queue_status,
    new_pipeline_id,
    prepare_queued_image_generation,
    should_queue_age_span,
    step_priority,
)
from characteros.services.evolution import EvolutionEngine
from characteros.storage.local_characters import LocalCharacterService
from characteros.storage.local_queue import LocalQueueManager
from narratron.charpass.schema import empty_manifest_dict
from narratron.charpass.style_prompt import build_image_prompt


def _styled_manifest() -> dict:
    data = empty_manifest_dict()
    data["_identity"]["name"] = "卡爾"
    data["_meta"]["entity_id"] = "character-卡爾"
    data["_style"]["outfit"]["description"] = "舊白色亞麻襯衫"
    data["_style"]["character_style"] = {
        "visual": {"medium": "cinematic realism", "aesthetic": "冷調都市"},
        "art_prompt": {"positive": "highly detailed face", "negative": "cartoon, watermark"},
        "consistency_notes": "臉必須一致",
    }
    return data


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


def test_age_span_steps_are_faces_then_tpose() -> None:
    steps = age_span_steps(age_start=1, age_end=3)
    assert [item["purpose"] for item in steps] == [
        "face_detail",
        "face_detail",
        "face_detail",
        "tpose",
        "tpose",
        "tpose",
    ]
    assert [item["age"] for item in steps] == [1, 2, 3, 1, 2, 3]
    assert steps[0]["depends_on"] is None
    assert initial_queue_status(steps[0]) == "pending"
    assert initial_queue_status(steps[1]) == "waiting"
    assert steps[1]["depends_on"] == {"phase": "face_detail", "age": 1}
    assert steps[3]["depends_on"] == {"phase": "face_detail", "age": 3}
    assert steps[4]["depends_on"] == {"phase": "tpose", "age": 1}


def test_full_age_span_covers_one_to_eighty() -> None:
    steps = age_span_steps()
    assert len(steps) == 160
    assert steps[0]["age"] == 1
    assert steps[79]["age"] == 80
    assert steps[80]["purpose"] == "tpose"
    assert steps[-1]["age"] == 80


def test_new_character_without_images_uses_age_span() -> None:
    assert should_queue_age_span("identity", {"_identity": {"name": "卡爾"}})
    assert should_queue_age_span("age_span", {"_identity": {"ref_images": [{"path": "assets/x.png"}]}})
    assert not should_queue_age_span("identity", {"_identity": {"ref_images": [{"path": "assets/x.png"}]}})
    assert not should_queue_age_span("outfit", {"_identity": {"name": "卡爾"}})


def test_face_prompt_includes_exact_age() -> None:
    data = _styled_manifest()
    data["_identity"]["age_visual"] = 12
    prompt = build_image_prompt(data, purpose="face_detail", multi_angle=False)
    assert "exactly 12 years old" in prompt["positive"]
    assert "extreme facial close-up" in prompt["positive"]


def test_tpose_prompt_locks_identity_and_t_pose() -> None:
    prompt = build_image_prompt(_styled_manifest(), purpose="tpose", multi_angle=False)
    assert prompt["angle"] == "tpose"
    assert "T-pose" in prompt["positive"]
    assert "T型體" in prompt["positive"]
    assert "single character only" in prompt["positive"]
    assert "same character identity as the face-detail references" in prompt["positive"]


def test_evolution_writes_age_appearance() -> None:
    evolved = EvolutionEngine().apply_evolution(_styled_manifest(), {"age_override": 7})
    assert evolved["_identity"]["age_visual"] == 7
    assert evolved["_identity"]["age_appearance"] == "7 years old"


def test_age_span_refs_use_previous_face_and_matching_face() -> None:
    pipeline_id = "age-span-demo"
    tasks = [
        {
            "status": "ready",
            "evolution_params": {
                "_image_request": {
                    "pipeline": "age_span",
                    "pipeline_id": pipeline_id,
                    "phase": "face_detail",
                    "purpose": "face_detail",
                    "age": 1,
                }
            },
            "result_metadata": {
                "image_generation": {
                    "images": [{"url": "https://cdn.example/face-1.png", "asset_path": "causal/review/a.png"}]
                }
            },
        },
        {
            "status": "ready",
            "evolution_params": {
                "_image_request": {
                    "pipeline": "age_span",
                    "pipeline_id": pipeline_id,
                    "phase": "face_detail",
                    "purpose": "face_detail",
                    "age": 2,
                }
            },
            "result_metadata": {
                "image_generation": {
                    "images": [{"url": "https://cdn.example/face-2.png"}]
                }
            },
        },
    ]
    face_three = collect_age_span_ref_uris(
        tasks,
        {"pipeline_id": pipeline_id, "phase": "face_detail", "age": 3},
    )
    assert face_three == ["https://cdn.example/face-2.png"]
    tpose_two = collect_age_span_ref_uris(
        tasks,
        {"pipeline_id": pipeline_id, "phase": "tpose", "age": 2},
    )
    assert tpose_two[0] == "https://cdn.example/face-2.png"


def test_age_span_refs_use_lock_url_and_manifest() -> None:
    pipeline_id = "age-span-lock"
    previous = {
        "status": "ready",
        "evolution_params": {
            "_image_request": {
                "pipeline": "age_span",
                "pipeline_id": pipeline_id,
                "phase": "face_detail",
                "purpose": "face_detail",
                "age": 4,
            }
        },
        "result_metadata": {
            "lock_url": "https://cdn.example/face-4-lock.png",
            "image_generation": {
                "images": [{"asset_path": "assets/face_detail/age_004/ref.png"}]
            },
        },
    }
    face_five = collect_age_span_ref_uris(
        [previous],
        {"pipeline_id": pipeline_id, "phase": "face_detail", "age": 5},
    )
    assert face_five == ["https://cdn.example/face-4-lock.png"]

    manifest = {
        "_extensions": {
            "image_gen": {
                "age_span": {
                    "faces": {
                        "7": [{"uri": "https://cdn.example/face-7.png", "path": "assets/face_detail/age_007/x.png"}]
                    }
                }
            }
        }
    }
    face_eight = collect_age_span_ref_uris(
        [],
        {"pipeline_id": pipeline_id, "phase": "face_detail", "age": 8},
        manifest=manifest,
    )
    assert face_eight == ["https://cdn.example/face-7.png"]


def test_later_age_span_refs_ignore_identity_seed() -> None:
    pipeline_id = "age-span-demo"
    previous = {
        "status": "ready",
        "evolution_params": {
            "_image_request": {
                "pipeline": "age_span",
                "pipeline_id": pipeline_id,
                "phase": "face_detail",
                "purpose": "face_detail",
                "age": 2,
            }
        },
        "result_metadata": {
            "image_generation": {
                "images": [{"url": "https://cdn.example/face-2.png"}]
            }
        },
    }
    refs = collect_age_span_ref_uris(
        [previous],
        {"pipeline_id": pipeline_id, "phase": "face_detail", "age": 3},
        seed_uris=["https://cdn.example/adult-identity.png"],
    )
    assert refs == ["https://cdn.example/face-2.png"]


def test_queue_age_span_enqueues_only_the_next_step(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    listed = service.list_characters()
    core_id = listed["items"][0].id
    pipeline_id = new_pipeline_id()
    queue = LocalQueueManager(local_root)
    first_step = age_span_steps(age_start=1, age_end=2)[0]
    task, is_new = queue.request_variant_generation(
        core_id=core_id,
        evolution_params=build_age_span_evolution_params(
            first_step,
            pipeline_id=pipeline_id,
            extra="keep scars",
            provider="null",
        ),
        priority=step_priority(0, first_step),
        character_name="測試角色",
        status="pending",
    )
    assert is_new
    tasks = queue.list_tasks(core_id=core_id, limit=20)
    assert len(tasks) == 1
    assert tasks[0]["status"] == "pending"
    first_req = tasks[0]["evolution_params"]["_image_request"]
    assert first_req["purpose"] == "face_detail"
    assert first_req["age"] == 1
    assert first_req["multi_angle"] is False
    assert first_req["total_steps"] == 4
    assert "keep scars" in first_req["extra"]
    assert first_req["user_extra"] == "keep scars"

    processed = queue.process_next(character_service=service, core_id=core_id)
    assert processed is not None
    assert processed["status"] == "ready"
    follow = [item for item in queue.list_tasks(core_id=core_id, limit=20) if item["id"] != processed["id"]]
    assert len(follow) == 1
    next_req = follow[0]["evolution_params"]["_image_request"]
    assert follow[0]["status"] == "pending"
    assert next_req["purpose"] == "face_detail"
    assert next_req["age"] == 2
    assert next_req["user_extra"] == "keep scars"


def test_process_age_span_injects_previous_refs(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    listed = service.list_characters()
    core_id = listed["items"][0].id
    pipeline_id = new_pipeline_id()
    queue = LocalQueueManager(local_root)
    first_step = age_span_steps(age_start=1, age_end=2)[0]
    queue.request_variant_generation(
        core_id=core_id,
        evolution_params=build_age_span_evolution_params(
            first_step,
            pipeline_id=pipeline_id,
            provider="null",
        ),
        priority=step_priority(0, first_step),
        character_name="測試角色",
        status="pending",
    )
    pending = queue.list_tasks(status="pending", core_id=core_id, limit=10)
    waiting = queue.list_tasks(status="waiting", core_id=core_id, limit=10)
    assert len(pending) == 1
    assert len(waiting) == 0
    first = queue.process_next(character_service=service, core_id=core_id)
    assert first is not None
    assert first["status"] == "ready"
    assert first["evolution_params"]["_image_request"]["age"] == 1
    prompt = first["result_metadata"]["image_generation"]["prompt"]
    assert "exactly 1 years old" in prompt
    second = queue.process_next(character_service=service, core_id=core_id)
    assert second is not None
    refs = second["result_metadata"]["image_generation"].get("ref_image_uris") or []
    assert refs
    prepared = prepare_queued_image_generation(
        {"_identity": {"name": "測試角色"}},
        second["evolution_params"]["_image_request"],
        sibling_tasks=queue.list_tasks(core_id=core_id, limit=20),
    )
    assert prepared["extra_ref_uris"]


def test_assemble_request_uses_age_filename_prefix() -> None:
    request = assemble_request(
        _styled_manifest(),
        purpose="face_detail",
        extra="exactly 5 years old",
        multi_angle=False,
        extra_fields={
            "filename_prefix": "ref_face_detail_age_005",
            "asset_dir": "assets/face_detail/age_005",
            "age": 5,
        },
    )
    assert request.extra["filename_prefix"] == "ref_face_detail_age_005"
    assert request.extra["age"] == 5
    assert request.extra["angle"] == "face_detail"


def test_process_age_span_faces_before_tpose(local_root: Path) -> None:
    service = LocalCharacterService(local_root)
    listed = service.list_characters()
    core_id = listed["items"][0].id
    pipeline_id = new_pipeline_id()
    queue = LocalQueueManager(local_root)
    first_step = age_span_steps(age_start=1, age_end=2)[0]
    queue.request_variant_generation(
        core_id=core_id,
        evolution_params=build_age_span_evolution_params(
            first_step,
            pipeline_id=pipeline_id,
            provider="null",
        ),
        priority=step_priority(0, first_step),
        character_name="測試角色",
        status="pending",
    )
    queue.process_next(character_service=service, core_id=core_id)
    pending = queue.list_tasks(status="pending", core_id=core_id, limit=10)
    waiting = queue.list_tasks(status="waiting", core_id=core_id, limit=10)
    assert len(pending) == 1
    assert pending[0]["evolution_params"]["_image_request"]["age"] == 2
    assert pending[0]["evolution_params"]["_image_request"]["phase"] == "face_detail"
    assert len(waiting) == 0

    queue.process_next(character_service=service, core_id=core_id)
    pending = queue.list_tasks(status="pending", core_id=core_id, limit=10)
    assert len(pending) == 1
    assert pending[0]["evolution_params"]["_image_request"]["phase"] == "tpose"
    assert pending[0]["evolution_params"]["_image_request"]["age"] == 1


def test_local_queue_worker_pause_flag(local_root: Path) -> None:
    queue = LocalQueueManager(local_root)
    assert queue.get_worker_control()["paused"] is False
    queue.set_worker_paused(True)
    assert queue.get_worker_control()["paused"] is True
    queue.set_worker_paused(False)
    assert queue.get_worker_control()["paused"] is False


def test_age_one_uses_identity_https_seed_refs() -> None:
    pipeline_id = "age-span-seed"
    seed = ["https://cdn.example/identity-front.png", "assets/identity/front.png"]
    refs = collect_age_span_ref_uris(
        [],
        {"pipeline_id": pipeline_id, "phase": "face_detail", "age": 1},
        seed_uris=seed,
    )
    assert refs[0] == "https://cdn.example/identity-front.png"
    manifest = _styled_manifest()
    manifest["_identity"]["ref_images"] = [
        {
            "uri": "https://cdn.example/karl-front.png",
            "path": "assets/identity/ref_face_front_001.png",
            "angle": "front",
        }
    ]
    request = assemble_request(
        manifest,
        purpose="face_detail",
        extra="exactly 1 years old",
        multi_angle=False,
        extra_fields={"pipeline": "age_span", "age": 1},
    )
    assert "https://cdn.example/karl-front.png" in request.ref_image_uris


def test_age_span_later_request_does_not_merge_identity_seed() -> None:
    manifest = _styled_manifest()
    manifest["_identity"]["ref_images"] = [
        {
            "uri": "https://cdn.example/karl-adult.png",
            "path": "assets/identity/ref_face_front_001.png",
            "angle": "front",
        }
    ]
    request = assemble_request(
        manifest,
        purpose="face_detail",
        extra="exactly 6 years old",
        multi_angle=False,
        extra_ref_uris=["https://cdn.example/face-5.png"],
        extra_fields={"pipeline": "age_span", "age": 6},
    )
    assert request.ref_image_uris == ["https://cdn.example/face-5.png"]

