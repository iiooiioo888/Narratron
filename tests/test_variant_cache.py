"""變體快取：語意指紋、profile_version 失效、品質閘門。"""

from __future__ import annotations

from pathlib import Path

from characteros.services.evolution import EvolutionEngine
from characteros.services.quality_gate import evaluate_generation
from characteros.storage.local_characters import LocalCharacterService
from characteros.utils.hash import canonical_evolution_params, compute_variant_hash
from characteros.models.schema import CharacterEditorUpdateRequest


def test_canonical_hash_ignores_pipeline_and_nonce() -> None:
    left = {
        "age_override": 80,
        "_queue_nonce": "age-span-aaa",
        "_image_request": {
            "purpose": "face_detail",
            "age": 80,
            "pipeline_id": "pipe-1",
            "provider": "wan",
        },
    }
    right = {
        "age_override": 80,
        "_queue_nonce": "age-span-bbb",
        "_image_request": {
            "purpose": "face_detail",
            "age": 80,
            "pipeline_id": "pipe-2",
            "provider": "null",
        },
    }
    assert canonical_evolution_params(left) == {"age_override": 80, "purpose": "face_detail"}
    assert compute_variant_hash(1, 1, left) == compute_variant_hash(1, 1, right)


def test_profile_version_changes_variant_hash() -> None:
    params = {"age_override": 80, "purpose": "face_detail"}
    assert compute_variant_hash(1, 1, params) != compute_variant_hash(1, 2, params)


def test_emotion_and_weather_change_hash() -> None:
    base = {"age_override": 80, "purpose": "face_detail"}
    sad = {**base, "emotion_state": "sad"}
    rain = {**base, "weather": "rain"}
    assert compute_variant_hash(1, 1, base) != compute_variant_hash(1, 1, sad)
    assert compute_variant_hash(1, 1, base) != compute_variant_hash(1, 1, rain)


def test_evolution_applies_weather() -> None:
    evolved = EvolutionEngine().apply_evolution(
        {"_identity": {"name": "林默"}},
        {"age_override": 80, "weather": "rain", "emotion_state": "sad"},
    )
    assert evolved["_weather"]["condition"] == "rain"
    assert evolved["_expression"]["base_emotion"] == "sad"
    assert evolved["_identity"]["age_visual"] == 80


def test_quality_gate_requires_image() -> None:
    failed = evaluate_generation({}, provider_name="wan")
    assert failed.passed is False
    assert failed.reason == "missing_image"
    passed = evaluate_generation(
        {"images": [{"url": "https://cdn.example/x.png"}]},
        provider_name="null",
    )
    assert passed.passed is True


def test_editor_profile_version_invalidates_cache(tmp_path: Path) -> None:
    root = tmp_path / "charpasses"
    entity = root / "character-測試角色"
    entity.mkdir(parents=True)
    (entity / "current.charpass").write_text(
        '{"schema":"https://narratron.dev/schemas/charpass/v1.json",'
        '"_meta":{"character_name":"測試角色","profile_version":1},'
        '"_identity":{"name":"測試角色","age_appearance":"30"}}\n',
        encoding="utf-8",
    )
    service = LocalCharacterService(root)
    core_id = service.list_characters()["items"][0].id
    before = service.get_character_by_id(core_id)
    assert before.profile.version == 1
    editor = service.get_editor_payload(core_id)
    body = CharacterEditorUpdateRequest(
        name=editor.core.name,
        base_age=editor.core.base_age,
        gender_spectrum=editor.core.gender_spectrum,
        tags=list(editor.core.tags or []),
        metadata=dict(editor.core.metadata or {}),
        identity_anchor={"eye_color": "blue"},
        manifest={"_identity": {"name": editor.core.name, "eye_color": "blue"}},
        project_name=editor.profile.project_name,
        project_id=editor.profile.project_id,
        style_preset=editor.profile.style_preset,
        outfit_config=dict(editor.profile.outfit_config or {}),
        created_by=editor.profile.created_by,
        notes=editor.profile.notes,
    )
    updated = service.update_character_editor(core_id, body)
    assert updated.profile.version >= 2
    old_hash = compute_variant_hash(core_id, 1, {"age_override": 80}, before.profile.manifest)
    new_hash = compute_variant_hash(
        core_id,
        updated.profile.version,
        {"age_override": 80},
        updated.profile.manifest,
    )
    assert old_hash != new_hash


def test_short_aliases_share_canonical_hash() -> None:
    left = {"age": 80, "emotion": "sad", "scene": "battle"}
    right = {"age_override": 80, "emotion_state": "sad", "scene_context": "battle"}
    assert canonical_evolution_params(left) == canonical_evolution_params(right)
    assert compute_variant_hash(1, 1, left) == compute_variant_hash(1, 1, right)


def test_evolved_prompt_includes_weather_emotion_and_injury() -> None:
    from narratron.charpass.style_prompt import build_image_prompt

    evolved = EvolutionEngine().apply_evolution(
        {"_identity": {"name": "林默"}},
        {
            "age_override": 80,
            "weather": "rain",
            "emotion_state": "sad",
            "scene_context": "battle",
            "injury_level": 0.6,
        },
    )
    prompt = build_image_prompt(evolved, purpose="face_detail", multi_angle=False)
    text = prompt["positive"]
    assert "wet hair" in text or "rain" in text
    assert "sad" in text
    assert "battle" in text
    assert "visible bruises" in text or "visible injuries" in text
