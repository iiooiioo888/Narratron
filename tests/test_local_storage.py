"""本機 charpass 後備儲存測試。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from characteros.storage.local_characters import LocalCharacterService
from characteros.models.schema import CharacterEditorUpdateRequest


@pytest.fixture()
def local_root(tmp_path: Path) -> Path:
    root = tmp_path / "charpasses"
    entity_dir = root / "character-test"
    entity_dir.mkdir(parents=True)
    manifest = {
        "schema": "https://narratron.dev/schemas/charpass/v1.json",
        "_meta": {"character_name": "測試角色", "tags": ["demo"]},
        "_identity": {"name": "測試角色", "gender_spectrum": 0.4, "age_appearance": 30},
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
