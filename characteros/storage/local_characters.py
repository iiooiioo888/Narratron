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
ANGLE_SORT_ORDER = {
    "face_detail": 0,
    "front": 1,
    "three_quarter": 2,
    "left": 3,
    "right": 4,
    "back": 5,
    "top": 6,
    "bottom": 7,
}


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


def _first_ref_path(refs: Any, *preferred_angles: str) -> str | None:
    if not isinstance(refs, list):
        return None
    items = [item for item in refs if isinstance(item, dict)]
    for angle in preferred_angles:
        for item in items:
            if str(item.get("angle") or "").strip() == angle and str(item.get("path") or "").strip():
                return str(item.get("path")).strip()
    for item in items:
        path = str(item.get("path") or "").strip()
        if path:
            return path
    return None


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _sort_images(images: Any) -> list[dict[str, Any]]:
    if not isinstance(images, list):
        return []
    items = [dict(item) for item in images if isinstance(item, dict)]
    items.sort(
        key=lambda item: (
            ANGLE_SORT_ORDER.get(str(item.get("angle") or ""), 999),
            str(item.get("filename") or ""),
            str(item.get("asset_path") or ""),
        )
    )
    return items


def _images_by_angle_summary(images: Any) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in _sort_images(images):
        angle = str(item.get("angle") or "unclassified")
        grouped.setdefault(angle, []).append(item)
    return grouped


def _branch_summary(
    images: Any,
    *,
    kind: str = "image_gen",
    branch_id: str = "",
    purpose: str | None = None,
    status: str | None = None,
    review_status: str | None = None,
    updated_at: Any = None,
) -> dict[str, Any]:
    ordered_images = _sort_images(images)
    asset_paths = [
        str(item.get("asset_path") or "").strip()
        for item in ordered_images
        if str(item.get("asset_path") or "").strip()
    ]
    images_by_angle = _images_by_angle_summary(ordered_images)
    thumbnail_asset_path = _first_ref_path(
        [{"angle": item.get("angle"), "path": item.get("asset_path")} for item in ordered_images],
        "face_detail",
        "front",
        "three_quarter",
        "left",
        "right",
        "back",
        "top",
        "bottom",
    )
    face_detail_images = images_by_angle.get("face_detail") or []
    normalized_review_status = str(review_status or "").strip() or None
    normalized_status = str(status or "").strip() or "ready"
    effective_status = normalized_review_status or normalized_status
    angles = list(images_by_angle.keys())
    purpose_summary = str(purpose or kind or "branch").strip()
    angles_summary = ", ".join(angles)
    has_face_detail = bool(face_detail_images)
    image_count = len(asset_paths)
    sort_priority = 0 if str(purpose or "").strip() == "face_detail" else 1 if has_face_detail else 2
    status_summary = effective_status or normalized_status
    face_detail_summary = f"face_detail x{len(face_detail_images)}" if face_detail_images else ""
    return {
        "status": status_summary,
        "review_status": normalized_review_status,
        "effective_status": effective_status,
        "asset_paths": asset_paths,
        "angles": angles,
        "angles_summary": angles_summary,
        "images_by_angle": images_by_angle,
        "thumbnail_asset_path": thumbnail_asset_path,
        "face_detail_asset_path": (
            str(face_detail_images[0].get("asset_path") or "").strip() if face_detail_images else None
        ),
        "has_face_detail": has_face_detail,
        "face_detail_count": len(face_detail_images),
        "image_count": image_count,
        "purpose_summary": purpose_summary,
        "summary": " | ".join(
            part
            for part in (
                status_summary,
                purpose_summary,
                angles_summary,
                face_detail_summary,
                f"{image_count} images" if image_count else "",
            )
            if part
        ),
        "sort_key": f"{sort_priority}:{str(updated_at or '')}:{kind}:{branch_id}",
        "updated_at": updated_at,
    }


def _image_job_branches(folder: Path, character_id: int) -> list[dict[str, Any]]:
    image_root = folder / "causal" / "image_gen"
    if not image_root.is_dir():
        return []

    branches: list[dict[str, Any]] = []
    for purpose_dir in sorted(image_root.iterdir(), key=lambda item: item.name):
        if not purpose_dir.is_dir():
            continue
        for job_dir in sorted(purpose_dir.iterdir(), key=lambda item: item.name):
            if not job_dir.is_dir():
                continue
            full_response = _read_json_file(job_dir / "full-response.json")
            review = full_response.get("review") if isinstance(full_response.get("review"), dict) else {}
            images_index = _read_json_file(job_dir / "images-index.json")
            images = images_index.get("images") if isinstance(images_index.get("images"), list) else []
            review_status = str(review.get("status") or "").strip()
            branch_status = review_status or str(full_response.get("status") or "ready").strip() or "ready"
            summary = _branch_summary(
                images,
                kind="image_gen",
                branch_id=job_dir.name,
                purpose=purpose_dir.name,
                status=branch_status,
                review_status=review_status,
                updated_at=review.get("accepted_at")
                or review.get("rejected_at")
                or full_response.get("created_at")
                or _read_json_file(job_dir / "record.json").get("created_at"),
            )
            result_path = summary.get("thumbnail_asset_path") or (summary.get("asset_paths") or [None])[0]
            branches.append(
                {
                    "kind": "image_gen",
                    "branch_id": job_dir.name,
                    "label": f"image_gen/{purpose_dir.name}/{job_dir.name[:8]}",
                    "purpose": purpose_dir.name,
                    "job_id": job_dir.name,
                    **summary,
                    "result_url": (
                        f"/api/v1/characters/{character_id}/assets/{result_path}"
                        if isinstance(result_path, str) and result_path.strip()
                        else None
                    ),
                    "record_path": f"causal/image_gen/{purpose_dir.name}/{job_dir.name}/record.json",
                    "images_index_path": f"causal/image_gen/{purpose_dir.name}/{job_dir.name}/images-index.json",
                    "response_path": f"causal/image_gen/{purpose_dir.name}/{job_dir.name}/full-response.json",
                }
            )
    branches.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return branches


def _latest_image_branches(manifest: dict[str, Any], character_id: int) -> list[dict[str, Any]]:
    image_gen = manifest.get("_extensions", {}).get("image_gen", {})
    latest_by_purpose = image_gen.get("latest_by_purpose") if isinstance(image_gen, dict) else {}
    if not isinstance(latest_by_purpose, dict):
        return []

    branches: list[dict[str, Any]] = []
    for purpose, item in latest_by_purpose.items():
        if not isinstance(item, dict):
            continue
        summary = _branch_summary(
            [
                {
                    "angle": angle,
                    "asset_path": image.get("asset_path"),
                    "filename": image.get("filename") or image.get("asset_path"),
                }
                for angle, entries in (item.get("images_by_angle") or {}).items()
                for image in (entries if isinstance(entries, list) else [])
                if isinstance(image, dict)
            ]
            or [
                {"angle": angle, "asset_path": path, "filename": path}
                for angle, path in zip(item.get("angles") or [], item.get("asset_paths") or [])
            ]
            or [
                {"angle": None, "asset_path": path, "filename": path}
                for path in (item.get("asset_paths") or [])
            ],
            kind="image_gen",
            branch_id=str(item.get("job_id") or purpose),
            purpose=purpose,
            status="accepted",
            review_status="accepted",
            updated_at=item.get("updated_at"),
        )
        result_path = (
            item.get("thumbnail_asset_path")
            or summary.get("thumbnail_asset_path")
            or (summary.get("asset_paths") or [None])[0]
        )
        branches.append(
            {
                "kind": "image_gen",
                "branch_id": str(item.get("job_id") or purpose),
                "label": f"image_gen/{purpose}",
                "purpose": purpose,
                "job_id": item.get("job_id"),
                **summary,
                "result_url": (
                    f"/api/v1/characters/{character_id}/assets/{result_path}"
                    if isinstance(result_path, str) and result_path.strip()
                    else None
                ),
            }
        )
    return branches


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
        identity_refs = identity.get("ref_images") or []

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
        thumbnail_asset_path = str(meta.get("thumbnail") or "").strip() or _first_ref_path(
            identity_refs,
            "face_detail",
            "front",
            "three_quarter",
            "left",
            "right",
            "back",
            "top",
            "bottom",
        )
        face_detail_asset_path = _first_ref_path(identity_refs, "face_detail")
        if thumbnail_asset_path:
            metadata["thumbnail_asset_path"] = thumbnail_asset_path
        if face_detail_asset_path:
            metadata["face_detail_asset_path"] = face_detail_asset_path

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

    def save_charpass(
        self,
        character_id: int,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        entity_id = self._entity_id_for(character_id)
        existing = strip_local_sidecar(dict(self._read_manifest(entity_id)))
        next_manifest = strip_local_sidecar(dict(manifest or {}))
        meta = next_manifest.setdefault("_meta", {})
        identity = next_manifest.setdefault("_identity", {})

        if not meta.get("created_at"):
            meta["created_at"] = existing.get("_meta", {}).get("created_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        meta["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        meta["entity_id"] = entity_id
        if not meta.get("character_name"):
            meta["character_name"] = (
                identity.get("name")
                or existing.get("_meta", {}).get("character_name")
                or entity_id.removeprefix("character-")
            )
        if not identity.get("name"):
            identity["name"] = (
                meta.get("character_name")
                or existing.get("_identity", {}).get("name")
                or entity_id.removeprefix("character-")
            )
        age_appearance = identity.get("age_appearance")
        if isinstance(age_appearance, (int, float)):
            identity["age_appearance"] = str(age_appearance)

        self.store.write_manifest(entity_id, next_manifest)
        return strip_local_sidecar(dict(self._read_manifest(entity_id)))

    def get_version_summary(self, character_id: int) -> dict[str, Any]:
        entity_id = self._entity_id_for(character_id)
        folder = self.store.entity_dir(entity_id)
        manifest = strip_local_sidecar(dict(self._read_manifest(entity_id)))

        history_items: list[dict[str, Any]] = []
        for path in self.store.list_versions(entity_id):
            history_items.append(
                {
                    "name": path.name,
                    "path": path.relative_to(folder).as_posix() if path != folder else path.name,
                    "kind": "current" if path.name == "current.charpass" else "snapshot",
                    "is_binary": path.suffix == ".charpass" and path.name != "current.charpass",
                }
            )

        branches: list[dict[str, Any]] = []
        variants_dir = folder / "causal" / "variants"
        if variants_dir.is_dir():
            for path in sorted(variants_dir.iterdir(), key=lambda item: item.name):
                if not path.is_dir():
                    continue
                record_path = path / "record.json"
                record: dict[str, Any] = {}
                if record_path.is_file():
                    try:
                        record = json.loads(record_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        record = {}
                branches.append(
                    {
                        "kind": "variant",
                        "branch_id": path.name,
                        "label": f"variant/{path.name}",
                        "manifest_path": f"causal/variants/{path.name}/evolved-manifest.json",
                        "record_path": f"causal/variants/{path.name}/record.json",
                        "status": record.get("status") or "ready",
                        "review_status": None,
                        "effective_status": record.get("status") or "ready",
                        "purpose_summary": "variant",
                        "angles_summary": "",
                        "summary": "variant",
                        "has_face_detail": False,
                        "image_count": 0,
                        "asset_paths": [],
                        "angles": [],
                        "thumbnail_asset_path": None,
                        "face_detail_asset_path": None,
                        "updated_at": record.get("processed_at"),
                        "sort_key": f"2:{str(record.get('processed_at') or '')}:variant:{path.name}",
                    }
                )

        branches.extend(_image_job_branches(folder, character_id))
        existing_ids = {str(item.get("branch_id") or "") for item in branches}
        for branch in _latest_image_branches(manifest, character_id):
            if str(branch.get("branch_id") or "") in existing_ids:
                continue
            branches.append(branch)
        branches.sort(
            key=lambda item: (
                str(item.get("updated_at") or ""),
                str(item.get("sort_key") or ""),
            ),
            reverse=True,
        )
        for index, branch in enumerate(branches):
            branch["sort_order"] = index

        return {
            "entity_id": entity_id,
            "current_path": "current.charpass",
            "history": history_items,
            "branches": branches,
        }

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
            # 兼容中英文逗號（"," / "，"）
            raw = str(body.style_preset).replace("，", ",")
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            if parts:
                visual["medium"] = parts[0]
            if len(parts) > 1:
                visual["aesthetic"] = ", ".join(parts[1:])

        if body.notes is not None:
            extensions = manifest.setdefault("_extensions", {})
            extensions["notes"] = body.notes

        self._write_manifest_json(entity_id, manifest)
        return self.get_editor_payload(character_id)
