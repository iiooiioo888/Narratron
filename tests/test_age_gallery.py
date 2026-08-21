"""年齡圖庫：依歲數對應面部／T 型資產。"""

from __future__ import annotations

from pathlib import Path

from characteros.services.age_gallery import build_age_gallery, resolve_age_asset
from characteros.storage.local_characters import LocalCharacterService


def test_resolve_age_asset_prefers_canonical_paths(tmp_path: Path) -> None:
    folder = tmp_path / "character-demo"
    face = folder / "assets" / "face_detail" / "ref_face_detail_age_025_001.png"
    tpose = folder / "assets" / "tpose" / "age_025" / "ref_tpose_age_025_001.png"
    face.parent.mkdir(parents=True)
    tpose.parent.mkdir(parents=True)
    face.write_bytes(b"face")
    tpose.write_bytes(b"tpose")

    assert resolve_age_asset(folder, purpose="face_detail", age=25) == "assets/face_detail/ref_face_detail_age_025_001.png"
    assert resolve_age_asset(folder, purpose="tpose", age=25) == "assets/tpose/age_025/ref_tpose_age_025_001.png"
    assert resolve_age_asset(folder, purpose="face_detail", age=26) is None


def test_local_character_age_gallery(tmp_path: Path) -> None:
    root = tmp_path / "charpasses"
    entity = root / "character-測試角色"
    entity.mkdir(parents=True)
    manifest = {
        "schema": "https://narratron.dev/schemas/charpass/v1.json",
        "_meta": {"character_name": "測試角色", "tags": ["demo"]},
        "_identity": {"name": "測試角色", "gender_spectrum": 0.4, "age_appearance": "30"},
    }
    (entity / "current.charpass").write_text(
        __import__("json").dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    service = LocalCharacterService(root)
    core_id = service.list_characters()["items"][0].id
    entity_id = service._entity_id_for(core_id)
    folder = service.store.entity_dir(entity_id)
    face = folder / "assets" / "face_detail" / "ref_face_detail_age_003_001.png"
    face.parent.mkdir(parents=True, exist_ok=True)
    face.write_bytes(b"face-3")

    gallery = service.get_age_gallery(core_id, age_start=1, age_end=5)
    assert gallery["character_id"] == core_id
    assert gallery["face_count"] == 1
    item = next(entry for entry in gallery["items"] if entry["age"] == 3)
    assert item["has_face_detail"] is True
    assert item["face_detail_url"].endswith("assets/face_detail/ref_face_detail_age_003_001.png")
    assert item["has_tpose"] is False


def test_build_age_gallery_counts(tmp_path: Path) -> None:
    folder = tmp_path / "character-x"
    for age in (1, 2):
        path = folder / "assets" / "face_detail" / f"ref_face_detail_age_{age:03d}_001.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    tpose = folder / "assets" / "tpose" / "age_001" / "ref_tpose_age_001_001.png"
    tpose.parent.mkdir(parents=True, exist_ok=True)
    tpose.write_bytes(b"t")

    gallery = build_age_gallery(folder, character_id=9, character_name="X", age_start=1, age_end=3)
    assert gallery["face_count"] == 2
    assert gallery["tpose_count"] == 1
    assert len(gallery["items"]) == 3
