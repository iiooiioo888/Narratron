"""角色護照 API：export / import / lite / update / archive。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from narratron.api.app import app
from narratron.charpass.container import CharpassPacker
from narratron.charpass.schema import empty_manifest_dict


SCRIPT = "角色：\n- 莉娜：傷痕\n\nINT. 廢墟 - NIGHT\n莉娜站著。\n"


def _parse(client: TestClient) -> str:
    parsed = client.post("/parse", json={"script": SCRIPT, "persist": True})
    assert parsed.status_code == 200, parsed.text
    entity = next(item for item in parsed.json()["entities"] if item["name"] == "莉娜")
    return entity["id"]


def test_export_import_lite_update_archive(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CHARPASS_STORE_DIR", str(tmp_path))
    client = TestClient(app)
    char_id = _parse(client)

    exported = client.post(
        f"/api/v1/characters/{char_id}/export",
        json={"format": "charpass", "mode": "full", "as_json": True},
    )
    assert exported.status_code == 200, exported.text
    body = exported.json()
    assert body["checksum"].startswith("sha256:")
    assert body["size"] > 0

    file_resp = client.post(
        f"/api/v1/characters/{char_id}/export",
        json={"format": "charpass", "mode": "lite"},
    )
    assert file_resp.status_code == 200, file_resp.text
    assert file_resp.headers["content-type"].startswith("application/x-narratron-charpass")

    lite = client.get(f"/api/v1/characters/{char_id}/charpass")
    assert lite.status_code == 200, lite.text
    assert lite.json()["charpass"]["_identity"]["name"] == "莉娜"
    assert lite.json()["note"]

    updated = client.post(
        f"/api/v1/characters/{char_id}/charpass",
        json={"charpass": {"_style": {"ip_adapter_weight": 0.42}}},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["charpass"]["_style"]["ip_adapter_weight"] == 0.42
    assert updated.json()["note"] == lite.json()["note"]

    imported = client.post(
        f"/api/v1/projects/demo/characters/import",
        files={"file": ("lina.charpass", file_resp.content, "application/x-narratron-charpass")},
        data={"conflict_strategy": "create_new"},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["entity_id"] != char_id

    blocked = client.delete(f"/api/v1/characters/{char_id}")
    assert blocked.status_code == 409

    archived = client.delete(f"/api/v1/characters/{char_id}?archive=true")
    assert archived.status_code == 200
    assert archived.json()["archived"] is True


def test_overwrite_requires_confirm() -> None:
    client = TestClient(app)
    char_id = _parse(client)
    exported = client.post(
        f"/api/v1/characters/{char_id}/export",
        json={"format": "charpass", "mode": "lite"},
    )
    denied = client.post(
        "/api/v1/projects/demo/characters/import",
        files={"file": ("lina.charpass", exported.content, "application/x-narratron-charpass")},
        data={"conflict_strategy": "overwrite", "confirm": "false"},
    )
    assert denied.status_code == 409

    ok = client.post(
        "/api/v1/projects/demo/characters/import",
        files={"file": ("lina.charpass", exported.content, "application/x-narratron-charpass")},
        data={"conflict_strategy": "overwrite", "confirm": "true"},
    )
    assert ok.status_code == 200, ok.text


def test_import_foreign_charpass() -> None:
    client = TestClient(app)
    manifest = empty_manifest_dict()
    manifest["_identity"]["name"] = "卡爾"
    packed = CharpassPacker().pack(manifest)
    imported = client.post(
        "/api/v1/projects/demo/characters/import",
        files={"file": (packed.filename, packed.data, "application/x-narratron-charpass")},
        data={"conflict_strategy": "create_new"},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["name"] == "卡爾"
