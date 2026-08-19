"""`.charpass` 容器、校驗、版本、因果、Vault 橋接。"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from narratron.agents.parser import Parser
from narratron.agents.state import AgentState
from narratron.charpass.causal import apply_evolution_log, refresh_snapshot
from narratron.charpass.checksum import compute_checksum
from narratron.charpass.compat import check_version
from narratron.charpass.container import CharpassPacker, CharpassReader, PackedAsset
from narratron.charpass.exceptions import CharpassChecksumError, CharpassVersionError
from narratron.charpass.schema import empty_manifest_dict, manifest_to_dict
from narratron.charpass.store import CharpassStore
from narratron.charpass.vault_bridge import import_unpacked, merge_fill_missing
from narratron.vault.memory import InMemoryStore
from narratron.vault.schema import Entity, EntityKind
from narratron.vault.state_vault import StateVault


def _base_manifest(name: str = "莉娜") -> dict:
    data = empty_manifest_dict()
    data["_identity"]["name"] = name
    data["_meta"]["entity_id"] = f"character-{name}"
    return data


def test_zip_roundtrip_and_unknown_fields() -> None:
    manifest = _base_manifest()
    manifest["_identity"]["custom_mark"] = "keep-me"
    packed = CharpassPacker().pack(manifest, [PackedAsset(name="ref.bin", data=b"ref-bytes", uri="mem://ref")])
    opened = CharpassReader().read(packed.data)
    assert opened.manifest["_identity"]["name"] == "莉娜"
    assert opened.manifest["_identity"]["custom_mark"] == "keep-me"
    assert opened.manifest["_extensions"]["comfyui"]["path"] == ""
    assert packed.checksum.startswith("sha256:")
    assert packed.filename.endswith(".charpass")


def test_version_reject_two_majors_ahead() -> None:
    with pytest.raises(CharpassVersionError):
        check_version("3.0.0")
    warned = check_version("2.0.0")
    assert warned.warning
    assert warned.compatible is True


def test_checksum_detects_tamper() -> None:
    packed = CharpassPacker().pack(_base_manifest())
    with zipfile.ZipFile(BytesIO(packed.data), "r") as archive:
        members = {info.filename: archive.read(info.filename) for info in archive.infolist()}
    members["manifest.json"] = members["manifest.json"].replace("莉娜".encode("utf-8"), "卡爾".encode("utf-8"))
    tampered = BytesIO()
    with zipfile.ZipFile(tampered, "w") as archive:
        for name, blob in members.items():
            archive.writestr(name, blob)
    with pytest.raises(CharpassChecksumError):
        CharpassReader().read(tampered.getvalue())


def test_lite_threshold_strips_assets() -> None:
    packed = CharpassPacker().pack(
        _base_manifest(),
        [PackedAsset(name="assets/references/big.bin", data=b"x" * 2000, uri="mem://big")],
        lite_threshold_bytes=100,
    )
    assert packed.mode == "lite"
    opened = CharpassReader().read(packed.data)
    assert opened.assets == {}


def test_l1_hmac_and_l2_manifest_readable(tmp_path: Path) -> None:
    key = "unit-test-key"
    packed_l1 = CharpassPacker().pack(_base_manifest(), encryption_level=1, key=key)
    opened = CharpassReader().read(packed_l1.data, key=key)
    assert opened.encryption_level >= 1

    packed_l2 = CharpassPacker().pack(
        _base_manifest(),
        [PackedAsset(name="assets/references/a.bin", data=b"secret-asset", uri="mem://a")],
        encryption_level=2,
        key=key,
    )
    with zipfile.ZipFile(BytesIO(packed_l2.data), "r") as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["_identity"]["name"] == "莉娜"
    opened_l2 = CharpassReader().read(packed_l2.data, key=key)
    assert any(blob == b"secret-asset" for blob in opened_l2.assets.values())
    _ = tmp_path


def test_causal_patch_and_snapshot() -> None:
    log = [
        {"changes": ["+ _style.damage_regions scar", "→ _expression.default grimace"]},
        {"changes": [{"op": "-", "path": "_style.damage_regions", "value": "scar"}]},
    ]
    snapshot = apply_evolution_log({}, log)
    assert snapshot["_expression"]["default"] == "grimace"
    assert "scar" not in (snapshot.get("_style", {}).get("damage_regions") or [])
    manifest = {"_causal": {"evolution_log": [{"changes": ["+ _constraints.required bandage"]}]}}
    refresh_snapshot(manifest)
    assert "bandage" in manifest["_causal"]["current_state_snapshot"]["_constraints"]["required"]


def test_merge_overwrite_create_new_and_note_preserved() -> None:
    vault = StateVault(InMemoryStore())
    existing = Entity(
        id="character-莉娜",
        kind=EntityKind.CHARACTER,
        name="莉娜",
        payload={"note": "劇本備註", "continuity_tokens": ["scar"], "charpass": {"_identity": {"name": "莉娜", "species": "human"}}},
    )
    vault.upsert_entities([existing])
    packed = CharpassPacker().pack(
        {
            **_base_manifest(),
            "_identity": {"name": "莉娜", "species": "elf", "custom_mark": "incoming"},
        }
    )
    opened = CharpassReader().read(packed.data)

    merged = import_unpacked(vault, opened, strategy="merge")
    assert merged.payload["note"] == "劇本備註"
    assert merged.payload["charpass"]["_identity"]["species"] == "human"
    assert merged.payload["charpass"]["_identity"]["custom_mark"] == "incoming"

    with pytest.raises(Exception):
        import_unpacked(vault, opened, strategy="overwrite", confirm=False)

    overwritten = import_unpacked(vault, opened, strategy="overwrite", confirm=True)
    assert overwritten.payload["note"] == "劇本備註"
    assert overwritten.payload["charpass"]["_identity"]["species"] == "elf"

    created = import_unpacked(vault, opened, strategy="create_new")
    assert created.id != existing.id
    assert created.name == "莉娜"


def test_parser_keeps_charpass_and_projects_tokens() -> None:
    vault = StateVault(InMemoryStore())
    vault.upsert_entities(
        [
            Entity(
                id="character-莉娜",
                kind=EntityKind.CHARACTER,
                name="莉娜",
                payload={
                    "note": "舊",
                    "continuity_tokens": [],
                    "charpass": {
                        "_identity": {"name": "莉娜"},
                        "_style": {"damage_regions": [{"token": "wear", "region": "clothing", "note": "", "source": "manual"}]},
                    },
                },
            )
        ]
    )
    state = Parser(vault=vault).parse(AgentState(script="角色：\n- 莉娜：左頰傷痕與舊繃帶\n"))
    lina = next(item for item in state.entities if item.name == "莉娜")
    assert lina.payload["note"]
    assert "scar" in lina.payload["continuity_tokens"]
    passport = lina.payload["charpass"]
    tokens = {item["token"] for item in passport["_style"]["damage_regions"]}
    assert "wear" in tokens
    assert "scar" in tokens
    assert "bandage" in tokens


def test_store_keeps_five_versions(tmp_path: Path) -> None:
    store = CharpassStore(tmp_path)
    for index in range(7):
        store.write("character-lina", f"blob-{index}".encode("utf-8"))
    assert len(store.list_versions("character-lina")) == 5


def test_checksum_excludes_self() -> None:
    members = {
        "manifest.json": json.dumps({"_meta": {"checksum": "sha256:deadbeef"}, "_identity": {"name": "A"}}).encode(),
        "schema.json": b"{}",
        "signature.sig": b"not-hashed",
    }
    left = compute_checksum(members)
    members["signature.sig"] = b"changed"
    assert compute_checksum(members) == left


def test_merge_fill_missing_keeps_conflict() -> None:
    merged = merge_fill_missing({"a": 1, "b": {}}, {"a": 9, "b": {"c": 2}, "d": 3})
    assert merged["a"] == 1
    assert merged["b"]["c"] == 2
    assert merged["d"] == 3


def test_manifest_to_dict_roundtrip() -> None:
    data = _base_manifest()
    data["_extensions"]["comfyui"]["version"] = "0"
    dumped = manifest_to_dict(data)
    assert dumped["_extensions"]["comfyui"]["version"] == "0"
