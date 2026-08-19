"""本機 charpass 角色後端：讀寫 data/charpasses/，無需 PostgreSQL。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException, status

from characteros.models.schema import (
    CharacterCoreResponse,
    CharacterEditorResponse,
    CharacterEditorUpdateRequest,
    CharacterFullResponse,
    CharacterProfileResponse,
)
from narratron.charpass.schema import LOCAL_CURRENT_FILE, strip_local_sidecar
from narratron.charpass.store import CharpassStore, sidecar_manifest

INDEX_FILENAME = ".characteros-index.json"


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _stable_uuid(entity_id: str, manifest: dict[str, Any]) -> str:
    meta = manifest.get("_meta") or {}
    charpass_id = meta.get("charpass_id")
    if isinstance(charpass_id, str) and charpass_id.strip():
        return charpass_id.strip()
    return str(uuid5(NAMESPACE_URL, f"characteros-local:{entity_id}"))


class LocalCharacterService:
    """以 data/charpasses/ 為來源的角色 CRUD（測試／離線用）。"""

    def __init__(self, root: str | Path | None = None) -> None:
        self.store = CharpassStore(root)
        self.root = self.store.root
        self._index_path = self.root / INDEX_FILENAME

    def _load_index(self) -> dict[str, Any]:
        if not self._index_path.is_file():
            return {"next_id": 1, "entities": {}, "reverse": {}}
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"next_id": 1, "entities": {}, "reverse": {}}
        if not isinstance(data, dict):
            return {"next_id": 1, "entities": {}, "reverse": {}}
        data.setdefault("next_id", 1)
        data.setdefault("entities", {})
        data.setdefault("reverse", {})
        return data

    def _save_index(self, index: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _discover_entity_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        ids: list[str] = []
        for folder in sorted(self.root.iterdir()):
            if not folder.is_dir():
                continue
            if folder.name.startswith("."):
                continue
            current = folder / "current.charpass"
            if current.is_file():
                ids.append(folder.name)
        return ids

    def _sync_index(self, index: dict[str, Any]) -> dict[str, Any]:
        entities: dict[str, str] = dict(index.get("entities") or {})
        reverse: dict[str, int] = {str(k): int(v) for k, v in (index.get("reverse") or {}).items()}
        next_id = int(index.get("next_id") or 1)

        for entity_id in self._discover_entity_ids():
            if entity_id in reverse:
                continue
            while str(next_id) in entities:
                next_id += 1
            entities[str(next_id)] = entity_id
            reverse[entity_id] = next_id
            next_id += 1

        stale_ids = [eid for eid, folder in entities.items() if not (self.root / folder).is_dir()]
        for stale in stale_ids:
            folder = entities.pop(stale, None)
            if folder and folder in reverse:
                reverse.pop(folder, None)

        index["entities"] = entities
        index["reverse"] = reverse
        index["next_id"] = next_id
        return index

    def _entity_id_for(self, character_id: int) -> str:
        index = self._sync_index(self._load_index())
        self._save_index(index)
        entity_id = (index.get("entities") or {}).get(str(character_id))
        if not entity_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character with id {character_id} not found",
            )
        return entity_id

    def _read_manifest(self, entity_id: str) -> dict[str, Any]:
        manifest = self.store.read_current_manifest(entity_id)
        if not manifest:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character with entity_id {entity_id} not found",
            )
        return manifest

    def _manifest_to_core(self, character_id: int, entity_id: str, manifest: dict[str, Any]) -> CharacterCoreResponse:
        meta = manifest.get("_meta") or {}
        identity = manifest.get("_identity") or {}
        blend = identity.get("blend") or {}

        name = (
            identity.get("name")
            or meta.get("character_name")
            or entity_id.removeprefix("character-")
            or entity_id
        )
        gender = identity.get("gender_spectrum")
        if gender is None:
            gender = blend.get("gender_spectrum")

        age = identity.get("age_appearance")
        if age is None:
            age = blend.get("age_visual")
        if age is None:
            offset = blend.get("age_offset")
            age = 25 + int(offset or 0)
        try:
            base_age = int(age)
        except (TypeError, ValueError):
            base_age = 25

        identity_anchor = {
            k: identity[k]
            for k in (
                "ref_images",
                "face_embedding",
                "ip_adapter",
                "blend",
                "lock_rules",
                "face_id",
                "face_threshold",
                "species",
            )
            if k in identity
        }

        metadata = dict(meta)
        for key in (
            "format",
            "format_version",
            "charpass_id",
            "character_name",
            "created_at",
            "updated_at",
            "entity_id",
            "tags",
        ):
            metadata.pop(key, None)

        return CharacterCoreResponse(
            id=character_id,
            uuid=_stable_uuid(entity_id, manifest),
            name=str(name),
            codename=entity_id if entity_id != str(name) else None,
            gender_spectrum=gender,
            base_age=max(0, min(150, base_age)),
            identity_anchor=identity_anchor,
            tags=list(meta.get("tags") or []),
            metadata=metadata,
            created_at=_parse_dt(meta.get("created_at")),
            updated_at=_parse_dt(meta.get("updated_at")),
        )

    def _manifest_to_profile(
        self,
        character_id: int,
        entity_id: str,
        manifest: dict[str, Any],
    ) -> CharacterProfileResponse:
        meta = manifest.get("_meta") or {}
        style = manifest.get("_style") or {}
        body = manifest.get("_body") or {}
        extensions = manifest.get("_extensions") or {}

        style_preset = None
        character_style = style.get("character_style") or {}
        visual = character_style.get("visual") or {}
        if isinstance(visual, dict):
            medium = visual.get("medium") or ""
            aesthetic = visual.get("aesthetic") or ""
            joined = ", ".join(x for x in (medium, aesthetic) if x)
            style_preset = joined or None

        outfit_config: dict[str, Any] = {}
        if isinstance(body, dict):
            outfit_config = {
                k: body[k]
                for k in ("template", "skeleton", "outfit", "accessories")
                if k in body
            }

        notes = extensions.get("notes") if isinstance(extensions, dict) else None

        return CharacterProfileResponse(
            id=character_id,
            core_id=character_id,
            version=1,
            is_active=True,
            project_name=meta.get("project_name"),
            project_id=meta.get("project_id"),
            manifest=strip_local_sidecar(dict(manifest)),
            style_preset=style_preset,
            outfit_config=outfit_config,
            created_by=meta.get("created_by"),
            notes=str(notes) if notes is not None else None,
            created_at=_parse_dt(meta.get("created_at")),
            updated_at=_parse_dt(meta.get("updated_at")),
        )

    def _write_manifest_json(self, entity_id: str, manifest: dict[str, Any]) -> None:
        """直接寫入 L0 JSON，略過 ZIP 打包（離線測試用）。"""
        folder = self.store.entity_dir(entity_id)
        folder.mkdir(parents=True, exist_ok=True)
        cleaned = strip_local_sidecar(dict(manifest))
        path = folder / LOCAL_CURRENT_FILE
        path.write_text(
            json.dumps(sidecar_manifest(cleaned), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def list_characters(
        self,
        skip: int = 0,
        limit: int = 20,
        name_filter: Optional[str] = None,
        tags_filter: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        index = self._sync_index(self._load_index())
        self._save_index(index)
        entities: dict[str, str] = index.get("entities") or {}

        items: list[CharacterCoreResponse] = []
        for cid_str in sorted(entities.keys(), key=lambda x: int(x)):
            entity_id = entities[cid_str]
            manifest = self.store.read_current_manifest(entity_id)
            if not manifest:
                continue
            core = self._manifest_to_core(int(cid_str), entity_id, manifest)
            if name_filter and name_filter.lower() not in core.name.lower():
                continue
            if tags_filter and not any(tag in core.tags for tag in tags_filter):
                continue
            items.append(core)

        total = len(items)
        page = items[skip : skip + limit]
        return {"items": page, "total": total, "skip": skip, "limit": limit}

    def get_character_by_id(self, character_id: int) -> CharacterFullResponse:
        entity_id = self._entity_id_for(character_id)
        manifest = self._read_manifest(entity_id)
        core = self._manifest_to_core(character_id, entity_id, manifest)
        profile = self._manifest_to_profile(character_id, entity_id, manifest)
        return CharacterFullResponse(core=core, profile=profile, available_variants=[])

    def get_editor_payload(self, character_id: int) -> CharacterEditorResponse:
        full = self.get_character_by_id(character_id)
        assert full.profile is not None
        return CharacterEditorResponse(core=full.core, profile=full.profile)

    def update_character_editor(
        self,
        character_id: int,
        body: CharacterEditorUpdateRequest,
    ) -> CharacterEditorResponse:
        entity_id = self._entity_id_for(character_id)
        manifest = strip_local_sidecar(dict(self._read_manifest(entity_id)))

        meta = manifest.setdefault("_meta", {})
        identity = manifest.setdefault("_identity", {})
        blend = identity.setdefault("blend", {})
        style = manifest.setdefault("_style", {})
        body_section = manifest.setdefault("_body", {})

        meta["character_name"] = body.name
        meta["entity_id"] = entity_id
        meta["tags"] = body.tags or []
        meta["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if body.project_id is not None:
            meta["project_id"] = body.project_id
        if body.created_by is not None:
            meta["created_by"] = body.created_by
        meta.update(body.metadata or {})

        identity["name"] = body.name
        if body.gender_spectrum is not None:
            identity["gender_spectrum"] = body.gender_spectrum
            blend["gender_spectrum"] = body.gender_spectrum
        identity["age_appearance"] = str(body.base_age)
        for key, value in (body.identity_anchor or {}).items():
            identity[key] = value

        if body.outfit_config:
            for key, value in body.outfit_config.items():
                body_section[key] = value

        if body.manifest:
            for key, value in body.manifest.items():
                manifest[key] = value

        if body.style_preset:
            character_style = style.setdefault("character_style", {})
            visual = character_style.setdefault("visual", {})
            parts = [p.strip() for p in body.style_preset.split(",") if p.strip()]
            if parts:
                visual["medium"] = parts[0]
            if len(parts) > 1:
                visual["aesthetic"] = ", ".join(parts[1:])

        if body.notes is not None:
            extensions = manifest.setdefault("_extensions", {})
            extensions["notes"] = body.notes

        self._write_manifest_json(entity_id, manifest)
        return self.get_editor_payload(character_id)
