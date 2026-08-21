"""角色護照 API：/api/v1 characters export/import/lite/update/archive。"""

from __future__ import annotations

import io
from typing import Any, Literal

from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from narratron.api.settings import get_settings
from narratron.charpass.container import CharpassPacker, CharpassReader
from narratron.charpass.exceptions import (
    CharpassArchiveOnlyError,
    CharpassChecksumError,
    CharpassConflictError,
    CharpassCryptoError,
    CharpassError,
    CharpassSignatureError,
    CharpassVersionError,
)
from narratron.charpass.schema import MIME_TYPE
from narratron.charpass.store import CharpassStore
from narratron.charpass.vault_bridge import (
    apply_manifest_to_entity,
    archive_entity,
    entity_to_manifest,
    import_unpacked,
    overlay_manifest,
    packed_from_entity,
)
from narratron.vault.schema import Entity, EntityKind
from narratron.vault.state_vault import StateVault, get_default_vault

MAX_CHARPASS_UPLOAD_BYTES = 32 * 1024 * 1024

v1_router = APIRouter()
_packer = CharpassPacker()
_reader = CharpassReader()

ConflictStrategy = Literal["create_new", "merge", "overwrite"]


class ExportBody(BaseModel):
    format: Literal["charpass"] = "charpass"
    mode: Literal["full", "lite"] = "full"
    include_assets: bool = True
    encryption_level: int | str = 0
    include_causal_history: bool = True
    include_voice: bool = True
    key: str | None = None
    as_json: bool = False


class CharpassWriteBody(BaseModel):
    charpass: dict[str, Any] = Field(default_factory=dict)


def _vault() -> StateVault:
    return get_default_vault()


def _store() -> CharpassStore:
    return CharpassStore(get_settings().charpass_store_dir)


def _encryption_level(value: int | str | None) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    mapping = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "0": 0, "1": 1, "2": 2, "3": 3}
    if value in mapping:
        return mapping[value]
    try:
        return int(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"不支援的 encryption_level={value}") from exc


def _content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _character_or_404(char_id: str) -> Entity:
    entity = _vault().get_entity(char_id)
    if entity is None or entity.kind is not EntityKind.CHARACTER:
        raise HTTPException(status_code=404, detail=f"找不到角色 {char_id}")
    return entity


def _http_charpass(exc: Exception) -> HTTPException:
    if isinstance(exc, CharpassVersionError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, (CharpassChecksumError, CharpassSignatureError, CharpassCryptoError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, CharpassConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, CharpassArchiveOnlyError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, CharpassError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@v1_router.post("/characters/{char_id}/export")
def export_character(char_id: str, body: ExportBody) -> Any:
    if body.format != "charpass":
        raise HTTPException(status_code=400, detail="目前僅支援 format=charpass")
    entity = _character_or_404(char_id)
    level = _encryption_level(body.encryption_level)
    try:
        packed = packed_from_entity(
            _vault(),
            entity,
            _packer,
            mode=body.mode,
            encryption_level=level,
            key=body.key,
            include_assets=body.include_assets,
            include_causal_history=body.include_causal_history,
            include_voice=body.include_voice,
        )
    except CharpassError as exc:
        raise _http_charpass(exc) from exc
    _store().write(entity.id, packed.data, packed.filename)
    if body.as_json:
        return JSONResponse(
            {
                "filename": packed.filename,
                "checksum": packed.checksum,
                "size": packed.size,
                "mode": packed.mode,
                "encryption_level": packed.encryption_level,
            }
        )
    return StreamingResponse(
        io.BytesIO(packed.data),
        media_type=MIME_TYPE,
        headers={
            "Content-Disposition": _content_disposition(packed.filename),
            "X-Charpass-Checksum": packed.checksum,
            "X-Charpass-Size": str(packed.size),
        },
    )


@v1_router.post("/projects/{proj_id}/characters/import")
async def import_character(
    proj_id: str,
    file: UploadFile = File(...),
    conflict_strategy: ConflictStrategy = Form("create_new"),
    target_scene_offset: int = Form(0),
    confirm: bool = Form(False),
    key: str | None = Form(None),
) -> dict[str, Any]:
    blob = await file.read(MAX_CHARPASS_UPLOAD_BYTES + 1)
    if not blob:
        raise HTTPException(status_code=400, detail="上傳檔案是空的")
    if len(blob) > MAX_CHARPASS_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="上傳檔案超過 32MB 上限")
    try:
        unpacked = _reader.read(blob, key=key)
        entity = import_unpacked(
            _vault(),
            unpacked,
            strategy=conflict_strategy,
            project_id=proj_id,
            target_scene_offset=target_scene_offset,
            confirm=confirm,
            store=_store(),
        )
    except CharpassError as exc:
        raise _http_charpass(exc) from exc
    _store().write(entity.id, blob, file.filename)
    return {
        "entity_id": entity.id,
        "name": entity.name,
        "project_id": proj_id,
        "conflict_strategy": conflict_strategy,
        "checksum": unpacked.checksum,
        "warnings": unpacked.warnings,
        "note": entity.payload.get("note", ""),
        "continuity_tokens": entity.payload.get("continuity_tokens", []),
    }


@v1_router.get("/characters/{char_id}/charpass")
def get_charpass_lite(char_id: str) -> dict[str, Any]:
    entity = _character_or_404(char_id)
    traces = _vault().trace_log().list_for_entity(entity.id)
    assets = [item for item in _vault().get_assets() if item.entity_id == entity.id]
    manifest = entity_to_manifest(entity, traces=traces, assets=assets)
    manifest.setdefault("_meta", {})["mode"] = "lite"
    causal = manifest.get("_causal")
    if isinstance(causal, dict):
        causal = dict(causal)
        causal["evolution_log"] = []
        manifest["_causal"] = causal
    return {
        "entity_id": entity.id,
        "name": entity.name,
        "note": entity.payload.get("note", ""),
        "continuity_tokens": entity.payload.get("continuity_tokens", []),
        "charpass": manifest,
    }


@v1_router.post("/characters/{char_id}/charpass")
def update_charpass(char_id: str, body: CharpassWriteBody) -> dict[str, Any]:
    entity = _character_or_404(char_id)
    if not body.charpass:
        raise HTTPException(status_code=400, detail="缺少 charpass 物件")
    note = entity.payload.get("note", "")
    current = entity.payload.get("charpass") if isinstance(entity.payload.get("charpass"), dict) else {}
    merged = overlay_manifest(current if isinstance(current, dict) else {}, body.charpass)
    entity = apply_manifest_to_entity(entity, merged, strategy="overwrite")
    entity.payload["note"] = note
    _vault().upsert_entities([entity])
    return {
        "entity_id": entity.id,
        "charpass": entity.payload.get("charpass"),
        "note": entity.payload.get("note"),
        "continuity_tokens": entity.payload.get("continuity_tokens"),
    }


@v1_router.delete("/characters/{char_id}")
def delete_or_archive_character(
    char_id: str,
    archive: bool = Query(False),
) -> dict[str, Any]:
    entity = _character_or_404(char_id)
    traces = _vault().trace_log().list_for_entity(char_id)
    try:
        archive_entity(_vault(), entity, traces=traces, archive=archive)
    except CharpassArchiveOnlyError as exc:
        raise _http_charpass(exc) from exc
    if archive or traces:
        return {"entity_id": char_id, "archived": True, "deleted": False}
    _vault().delete_entity(char_id)
    return {"entity_id": char_id, "archived": False, "deleted": True}
