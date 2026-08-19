"""Entity.payload.charpass ↔ manifest；assets 註冊；因果補齊；傷痕雙向同步。"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal
from uuid import uuid4

from narratron.charpass.causal import offset_scene_index, refresh_snapshot
from narratron.charpass.container import PackedAsset, PackedCharpass, UnpackedCharpass
from narratron.charpass.exceptions import CharpassArchiveOnlyError, CharpassConflictError
from narratron.charpass.schema import (
    empty_manifest_dict,
    manifest_to_dict,
    new_charpass_id,
    parse_manifest,
    utcnow,
)
from narratron.charpass.store import CharpassStore
from narratron.vault.schema import Asset, Entity, EntityKind, TraceRecord
from narratron.vault.state_vault import StateVault

ConflictStrategy = Literal["create_new", "merge", "overwrite"]

_TOKEN_REGIONS = {
    "scar": "skin",
    "bandage": "skin",
    "rust": "prop",
    "wear": "clothing",
    "bloodstain": "clothing",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_empty(value: Any) -> bool:
    return value in (None, "", [], {})


def overlay_manifest(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(existing)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = overlay_manifest(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def merge_fill_missing(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(existing)
    for key, value in incoming.items():
        if key not in out or _is_empty(out[key]):
            out[key] = copy.deepcopy(value)
        elif isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = merge_fill_missing(out[key], value)
    return out


def damage_regions_from_tokens(tokens: Iterable[str], *, source: str = "parser") -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    for token in tokens:
        if not token:
            continue
        regions.append(
            {
                "token": token,
                "region": _TOKEN_REGIONS.get(token, "unspecified"),
                "note": "",
                "source": source,
            }
        )
    return regions


def tokens_from_damage_regions(regions: Iterable[Any]) -> list[str]:
    tokens: list[str] = []
    for item in regions:
        token = ""
        if isinstance(item, dict):
            token = str(item.get("token") or "")
        else:
            token = str(getattr(item, "token", "") or "")
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def project_tokens_into_charpass(charpass: dict[str, Any], tokens: Iterable[str]) -> dict[str, Any]:
    payload = copy.deepcopy(charpass)
    style = payload.setdefault("_style", {})
    regions = list(style.get("damage_regions") or [])
    existing = {item.get("token") for item in regions if isinstance(item, dict)}
    for region in damage_regions_from_tokens(tokens, source="parser"):
        if region["token"] not in existing:
            regions.append(region)
            existing.add(region["token"])
    style["damage_regions"] = regions
    return payload


def sync_continuity_and_damage(entity: Entity) -> Entity:
    payload = dict(entity.payload)
    tokens = list(payload.get("continuity_tokens") or [])
    charpass = payload.get("charpass")
    if not isinstance(charpass, dict):
        charpass = empty_manifest_dict()
        charpass["_identity"]["name"] = entity.name
        charpass["_meta"]["entity_id"] = entity.id
        payload["charpass"] = charpass
    charpass = project_tokens_into_charpass(charpass, tokens)
    region_tokens = tokens_from_damage_regions(charpass.get("_style", {}).get("damage_regions") or [])
    for token in region_tokens:
        if token not in tokens:
            tokens.append(token)
    payload["continuity_tokens"] = tokens
    payload["charpass"] = charpass
    entity.payload = payload
    return entity


def traces_to_evolution(traces: Iterable[TraceRecord]) -> list[dict[str, Any]]:
    log: list[dict[str, Any]] = []
    for record in traces:
        tokens = list((record.payload or {}).get("continuity_tokens") or [])
        changes: list[dict[str, Any]] = []
        for token in tokens:
            changes.append({"op": "+", "path": "_style.damage_regions", "value": token})
        log.append(
            {
                "at": record.happened_at.isoformat() if record.happened_at else None,
                "shot_id": record.shot_id,
                "cause": record.cause,
                "effect": record.effect,
                "changes": changes,
            }
        )
    return log


def entity_to_manifest(
    entity: Entity,
    *,
    traces: Iterable[TraceRecord] | None = None,
    assets: Iterable[Asset] | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    payload = dict(entity.payload)
    existing = payload.get("charpass")
    manifest = manifest_to_dict(existing if isinstance(existing, dict) else empty_manifest_dict())
    meta = manifest.setdefault("_meta", {})
    meta["entity_id"] = entity.id
    if project_id:
        meta["project_id"] = project_id
    if not meta.get("charpass_id"):
        meta["charpass_id"] = new_charpass_id()
    meta["updated_at"] = utcnow().isoformat()
    identity = manifest.setdefault("_identity", {})
    if not identity.get("name"):
        identity["name"] = entity.name
    if payload.get("note") and not identity.get("note"):
        identity["note"] = payload.get("note")
    constraints = manifest.setdefault("_constraints", {})
    for token in payload.get("continuity_tokens") or []:
        continuity = list(constraints.get("continuity") or [])
        if token not in continuity:
            continuity.append(token)
        constraints["continuity"] = continuity
    manifest = project_tokens_into_charpass(manifest, payload.get("continuity_tokens") or [])
    if traces:
        causal = manifest.setdefault("_causal", {})
        existing_log = list(causal.get("evolution_log") or [])
        incoming = traces_to_evolution(traces)
        seen = {(item.get("shot_id"), item.get("cause"), item.get("effect")) for item in existing_log if isinstance(item, dict)}
        for item in incoming:
            key = (item.get("shot_id"), item.get("cause"), item.get("effect"))
            if key not in seen:
                existing_log.append(item)
        causal["evolution_log"] = existing_log
        refresh_snapshot(manifest)
    if assets:
        style = manifest.setdefault("_style", {})
        images = list(style.get("reference_images") or [])
        voice = manifest.setdefault("_voice", {})
        samples = list(voice.get("samples") or [])
        for asset in assets:
            ref = {
                "id": asset.id,
                "kind": asset.kind,
                "uri": asset.uri,
                "embedded": None,
                "metadata": dict(asset.metadata or {}),
            }
            if asset.kind in {"voice", "voice_sample"}:
                if not any(item.get("id") == asset.id for item in samples if isinstance(item, dict)):
                    samples.append(ref)
            else:
                if not any(item.get("id") == asset.id for item in images if isinstance(item, dict)):
                    images.append(ref)
        style["reference_images"] = images
        voice["samples"] = samples
    parse_manifest(manifest)
    return manifest


def collect_packed_assets(manifest: dict[str, Any], vault_assets: Iterable[Asset] | None = None) -> list[PackedAsset]:
    packed: list[PackedAsset] = []
    seen: set[str] = set()

    def _add(uri: str, kind: str, name: str) -> None:
        if not uri or uri in seen:
            return
        seen.add(uri)
        path = Path(uri.replace("file://", ""))
        data = path.read_bytes() if path.is_file() else b""
        if not data:
            return
        packed.append(PackedAsset(name=name, data=data, uri=uri, kind=kind))

    style = manifest.get("_style") if isinstance(manifest.get("_style"), dict) else {}
    for index, item in enumerate(style.get("reference_images") or []):
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri") or "")
        _add(uri, str(item.get("kind") or "reference_image"), item.get("embedded") or f"assets/references/ref-{index}")
    voice = manifest.get("_voice") if isinstance(manifest.get("_voice"), dict) else {}
    if voice.get("sample_uri"):
        _add(str(voice["sample_uri"]), "voice", "assets/voice/sample")
    for index, item in enumerate(voice.get("samples") or []):
        if isinstance(item, dict):
            _add(str(item.get("uri") or ""), "voice", item.get("embedded") or f"assets/voice/sample-{index}")
    for asset in vault_assets or []:
        if not asset.uri:
            continue
        kind = "voice" if asset.kind in {"voice", "voice_sample"} else asset.kind
        folder = "voice" if kind == "voice" else "references"
        _add(asset.uri, kind, f"assets/{folder}/{asset.id}")
    return packed


def apply_manifest_to_entity(
    entity: Entity,
    manifest: dict[str, Any],
    *,
    strategy: ConflictStrategy = "merge",
) -> Entity:
    payload = dict(entity.payload)
    incoming = manifest_to_dict(manifest)
    incoming.setdefault("_meta", {})["entity_id"] = entity.id
    current = payload.get("charpass")
    if strategy == "overwrite" or not isinstance(current, dict):
        payload["charpass"] = incoming
    else:
        payload["charpass"] = merge_fill_missing(current, incoming)
    entity.payload = payload
    return sync_continuity_and_damage(entity)


def register_manifest_assets(
    vault: StateVault,
    entity_id: str,
    unpacked: UnpackedCharpass,
) -> list[Asset]:
    created: list[Asset] = []
    manifest = unpacked.manifest
    refs: list[dict[str, Any]] = []
    style = manifest.get("_style") if isinstance(manifest.get("_style"), dict) else {}
    voice = manifest.get("_voice") if isinstance(manifest.get("_voice"), dict) else {}
    refs.extend(item for item in (style.get("reference_images") or []) if isinstance(item, dict))
    refs.extend(item for item in (voice.get("samples") or []) if isinstance(item, dict))
    if voice.get("sample_uri"):
        refs.append({"id": "voice-sample", "kind": "voice", "uri": voice.get("sample_uri")})
    for ref in refs:
        asset_id = str(ref.get("id") or f"charpass-{entity_id}-{uuid4().hex[:8]}")
        uri = str(ref.get("uri") or "")
        embedded = ref.get("embedded")
        if embedded and embedded in unpacked.assets:
            uri = uri or f"charpass://{entity_id}/{embedded}"
        asset = Asset(
            id=asset_id,
            entity_id=entity_id,
            kind=str(ref.get("kind") or "reference_image"),
            uri=uri,
            metadata={"charpass": True, "embedded": embedded},
        )
        created.append(asset)
    if created:
        vault.upsert_assets(created)
    return created


def _remap_asset_uris(manifest: dict[str, Any], written: dict[str, Path]) -> None:
    mapping = {key: str(path) for key, path in written.items()}

    def patch(item: dict[str, Any]) -> None:
        embedded = item.get("embedded")
        if isinstance(embedded, str) and embedded in mapping:
            item["uri"] = mapping[embedded]
            return
        uri = str(item.get("uri") or "")
        if uri in mapping:
            item["uri"] = mapping[uri]

    style = manifest.get("_style") if isinstance(manifest.get("_style"), dict) else {}
    for item in style.get("reference_images") or []:
        if isinstance(item, dict):
            patch(item)
    identity = manifest.get("_identity") if isinstance(manifest.get("_identity"), dict) else {}
    for item in identity.get("ref_images") or []:
        if isinstance(item, dict):
            patch(item)
    voice = manifest.get("_voice") if isinstance(manifest.get("_voice"), dict) else {}
    for item in voice.get("samples") or []:
        if isinstance(item, dict):
            patch(item)
    sample_uri = voice.get("sample_uri")
    if isinstance(sample_uri, str) and sample_uri in mapping:
        voice["sample_uri"] = mapping[sample_uri]


def find_character_by_name(vault: StateVault, name: str) -> Entity | None:
    for entity in vault.get_entities():
        if entity.kind is EntityKind.CHARACTER and entity.name == name:
            return entity
    return None


def import_unpacked(
    vault: StateVault,
    unpacked: UnpackedCharpass,
    *,
    strategy: ConflictStrategy = "create_new",
    project_id: str | None = None,
    target_scene_offset: int = 0,
    confirm: bool = False,
    store: CharpassStore | None = None,
) -> Entity:
    manifest = copy.deepcopy(unpacked.manifest)
    if project_id:
        manifest.setdefault("_meta", {})["project_id"] = project_id
    if target_scene_offset:
        offset_scene_index(manifest, target_scene_offset)
    identity = manifest.get("_identity") if isinstance(manifest.get("_identity"), dict) else {}
    name = str(identity.get("name") or "未命名角色")
    existing = find_character_by_name(vault, name)
    if strategy == "overwrite":
        if not confirm:
            raise CharpassConflictError("overwrite 需要 confirm=true")
        if existing is None:
            existing = _new_character(name, project_id)
        entity = apply_manifest_to_entity(existing, manifest, strategy="overwrite")
    elif strategy == "merge" and existing is not None:
        entity = apply_manifest_to_entity(existing, manifest, strategy="merge")
    else:
        entity = apply_manifest_to_entity(_new_character(name, project_id), manifest, strategy="overwrite")
        if existing is not None and strategy == "create_new":
            suffix = uuid4().hex[:6]
            entity.id = f"{existing.id}-import-{suffix}"
            entity.payload.setdefault("charpass", {}).setdefault("_meta", {})["entity_id"] = entity.id
    if project_id:
        entity.payload["project_id"] = project_id
    vault.upsert_entities([entity])
    local_store = store or CharpassStore()
    if unpacked.assets:
        written = local_store.write_assets(entity.id, unpacked.assets)
        _remap_asset_uris(unpacked.manifest, written)
        charpass = entity.payload.get("charpass")
        if isinstance(charpass, dict):
            _remap_asset_uris(charpass, written)
            entity.payload["charpass"] = charpass
            vault.upsert_entities([entity])
    register_manifest_assets(vault, entity.id, unpacked)
    return entity


def _new_character(name: str, project_id: str | None) -> Entity:
    compact = name.strip() or "unnamed"
    entity_id = f"character-{compact}"[:96]
    payload: dict[str, Any] = {"note": "", "continuity_tokens": []}
    if project_id:
        payload["project_id"] = project_id
    return Entity(
        id=entity_id,
        kind=EntityKind.CHARACTER,
        name=name,
        payload=payload,
        created_at=_now(),
    )


def archive_entity(vault: StateVault, entity: Entity, *, traces: list[TraceRecord], archive: bool) -> Entity:
    if traces and not archive:
        raise CharpassArchiveOnlyError("此角色已被 Trace Log 引用，只准歸檔、不准刪")
    if not archive:
        return entity
    payload = dict(entity.payload)
    payload["archived"] = True
    entity.payload = payload
    vault.upsert_entities([entity])
    return entity


def packed_from_entity(
    vault: StateVault,
    entity: Entity,
    packer: Any,
    packed_cls: type[PackedCharpass] = PackedCharpass,
    **pack_kwargs: Any,
) -> PackedCharpass:
    _ = packed_cls
    traces = vault.trace_log().list_for_entity(entity.id)
    assets = [item for item in vault.get_assets() if item.entity_id == entity.id]
    manifest = entity_to_manifest(entity, traces=traces, assets=assets)
    blobs = collect_packed_assets(manifest, assets)
    parse_manifest(manifest)
    return packer.pack(manifest, blobs, **pack_kwargs)
