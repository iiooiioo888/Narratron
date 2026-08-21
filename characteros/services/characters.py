"""CharacterOS 角色查詢服務。"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, status

from characteros.models.orm import CharacterCore, CharacterProfile, CharacterVariant
from characteros.models.schema import (
    CharacterCoreResponse,
    CharacterFullResponse,
    CharacterProfileResponse,
    CharacterVariantResponse,
    CharacterEditorUpdateRequest,
    CharacterEditorResponse,
)
from characteros.services.branch_summary import (
    branch_sort_tuple as _branch_sort_tuple,
    branch_summary as _branch_summary,
    first_ref_path as _first_ref_path,
    review_rank as _review_rank,
    strip_final_asset_path_from_branch,
    summary_images_from_payload as _summary_images_from_payload,
)
from narratron.charpass.schema import empty_manifest_dict
from narratron.charpass.store import CharpassStore


def _augment_core_with_manifest(core: CharacterCore, manifest: dict[str, Any] | None) -> CharacterCoreResponse:
    payload = CharacterCoreResponse.model_validate(core)
    if not isinstance(manifest, dict):
        return payload
    meta = manifest.get("_meta") if isinstance(manifest.get("_meta"), dict) else {}
    identity = manifest.get("_identity") if isinstance(manifest.get("_identity"), dict) else {}
    refs = identity.get("ref_images") if isinstance(identity, dict) else []
    metadata = dict(payload.metadata or {})
    thumbnail_asset_path = str(meta.get("thumbnail") or "").strip() or _first_ref_path(
        refs,
        "face_detail",
        "front",
        "three_quarter",
        "left",
        "right",
        "back",
        "top",
        "bottom",
    )
    face_detail_asset_path = _first_ref_path(refs, "face_detail")
    if thumbnail_asset_path:
        metadata["thumbnail_asset_path"] = thumbnail_asset_path
    if face_detail_asset_path:
        metadata["face_detail_asset_path"] = face_detail_asset_path
    payload.metadata = metadata
    return payload


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _branch_quality_score(branch: dict[str, Any]) -> tuple[int, int, int]:
    images_by_angle = branch.get("images_by_angle") if isinstance(branch.get("images_by_angle"), dict) else {}
    return (
        _review_rank(branch.get("effective_status") or branch.get("review_status") or branch.get("status")),
        len(branch.get("asset_paths") or []),
        len(images_by_angle),
    )


def _variant_is_available(variant: CharacterVariant) -> bool:
    if str(variant.status or "").strip().lower() != "ready":
        return False
    metadata = variant.result_metadata if isinstance(variant.result_metadata, dict) else {}
    image_generation = metadata.get("image_generation")
    if not isinstance(image_generation, dict):
        return True
    review = image_generation.get("review") if isinstance(image_generation.get("review"), dict) else {}
    review_status = str(
        review.get("status")
        or image_generation.get("review_status")
        or metadata.get("review_status")
        or ""
    ).strip().lower()
    return review_status in {"", "accepted"}


def _dedupe_branches(branches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for branch in branches:
        key = (str(branch.get("kind") or ""), str(branch.get("branch_id") or ""))
        current = deduped.get(key)
        if current is None:
            deduped[key] = branch
            continue
        candidate_score = (_branch_quality_score(branch), str(branch.get("updated_at") or ""))
        current_score = (_branch_quality_score(current), str(current.get("updated_at") or ""))
        if candidate_score >= current_score:
            deduped[key] = branch
    return list(deduped.values())


def _image_job_branches(entity_id: str, character_id: int) -> list[dict[str, Any]]:
    folder = CharpassStore().entity_dir(entity_id)
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
            request_payload = _read_json_file(job_dir / "request.json")
            response_payload = _read_json_file(job_dir / "response.json")
            record_payload = _read_json_file(job_dir / "record.json")
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
                or record_payload.get("created_at"),
            )
            result_path = (
                summary.get("hero_asset_path")
                or summary.get("thumbnail_asset_path")
                or (summary.get("asset_paths") or [None])[0]
            )
            branches.append(
                {
                    "kind": "image_gen",
                    "branch_id": job_dir.name,
                    "label": f"image_gen/{purpose_dir.name}/{job_dir.name[:8]}",
                    "purpose": purpose_dir.name,
                    "job_id": job_dir.name,
                    "provider": full_response.get("provider") or images_index.get("provider") or record_payload.get("provider"),
                    "model": full_response.get("model") or images_index.get("model") or record_payload.get("model"),
                    "review": review,
                    "request": request_payload,
                    "response": response_payload,
                    "prompt": full_response.get("prompt") or request_payload.get("prompt"),
                    "negative_prompt": full_response.get("negative_prompt") or request_payload.get("negative_prompt"),
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
            item.get("face_detail_asset_path")
            or item.get("thumbnail_asset_path")
            or summary.get("hero_asset_path")
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
                "provider": item.get("provider"),
                "model": item.get("model"),
                "review": {"status": "accepted", "accepted_at": item.get("updated_at")},
                "response": {
                    "provider": item.get("provider"),
                    "model": item.get("model"),
                    "images_by_angle": item.get("images_by_angle") or {},
                    "asset_paths": item.get("asset_paths") or [],
                },
                **summary,
                "result_url": (
                    f"/api/v1/characters/{character_id}/assets/{result_path}"
                    if isinstance(result_path, str) and result_path.strip()
                    else None
                ),
            }
        )
    return branches


class CharacterService:
    """
    角色服務：提供唯讀查詢功能
    遵循「不存在即 404」原則
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_character_by_id(self, character_id: int) -> CharacterFullResponse:
        """
        取得角色完整資訊（Core + Active Profile）
        
        Args:
            character_id: 角色核心 ID
        
        Returns:
            CharacterFullResponse
        
        Raises:
            HTTPException 404 if not found
        """
        # 查詢 Core，並預載入 active profile
        core = self.db.query(CharacterCore).options(
            joinedload(CharacterCore.profiles)
        ).filter(CharacterCore.id == character_id).first()
        
        if not core:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character with id {character_id} not found"
            )
        
        # 取得 active profile（只取最新啟用版本）
        active_profile = None
        if core.profiles:
            active_profiles = [p for p in core.profiles if p.is_active]
            if active_profiles:
                active_profile = max(active_profiles, key=lambda x: x.version)
        
        # 查詢已生成的變體（status='ready'）
        ready_variants = self.db.query(CharacterVariant).filter(
            CharacterVariant.core_id == character_id,
            CharacterVariant.status == 'ready'
        ).limit(50).all()
        
        return CharacterFullResponse(
            core=CharacterCoreResponse.model_validate(core),
            profile=CharacterProfileResponse.model_validate(active_profile) if active_profile else None,
            available_variants=[
                CharacterVariantResponse.model_validate(v)
                for v in ready_variants
                if _variant_is_available(v)
            ]
        )
    
    def get_character_by_uuid(self, uuid: str) -> CharacterFullResponse:
        """
        透過 UUID 取得角色完整資訊
        
        Args:
            uuid: 角色 UUID 字串
        
        Returns:
            CharacterFullResponse
        
        Raises:
            HTTPException 404 if not found
        """
        core = self.db.query(CharacterCore).options(
            joinedload(CharacterCore.profiles).and_(CharacterProfile.is_active == True)
        ).filter(CharacterCore.uuid == uuid).first()
        
        if not core:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character with uuid {uuid} not found"
            )
        
        # 重用 get_character_by_id 的邏輯
        return self.get_character_by_id(core.id)
    
    def list_characters(
        self,
        skip: int = 0,
        limit: int = 20,
        name_filter: Optional[str] = None,
        tags_filter: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        列出角色（摘要資訊，支援分頁與過濾）
        
        Args:
            skip: 跳過數量（分頁）
            limit: 返回數量上限
            name_filter: 名稱模糊搜尋
            tags_filter: 標籤過濾（包含任一標籤即可）
        
        Returns:
            Dict with 'items', 'total', 'skip', 'limit'
        """
        query = self.db.query(CharacterCore).options(joinedload(CharacterCore.profiles))
        
        # 套用過濾條件
        if name_filter:
            query = query.filter(CharacterCore.name.ilike(f"%{name_filter}%"))
        
        if tags_filter:
            # PostgreSQL ARRAY 重疊運算子
            query = query.filter(CharacterCore.tags.overlap(tags_filter))
        
        # 計算總數
        total = query.count()
        
        # 分頁
        items = query.order_by(CharacterCore.created_at.desc()).offset(skip).limit(limit).all()
        
        enriched_items: list[CharacterCoreResponse] = []
        for item in items:
            active_profile = sorted(
                [p for p in item.profiles if p.is_active],
                key=lambda x: x.version,
                reverse=True,
            )[0] if any(p.is_active for p in item.profiles) else None
            manifest = active_profile.manifest if active_profile and isinstance(active_profile.manifest, dict) else None
            enriched_items.append(_augment_core_with_manifest(item, manifest))

        return {
            "items": enriched_items,
            "total": total,
            "skip": skip,
            "limit": limit
        }

    def ensure_character(
        self,
        name: str,
        *,
        base_age: int = 25,
        gender_spectrum: Optional[float] = None,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
    ) -> tuple[CharacterCoreResponse, bool]:
        cleaned = str(name or "").strip()
        if not cleaned:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="角色名稱不可為空")

        query = self.db.query(CharacterCore)
        existing = query.filter(CharacterCore.name == cleaned).first()
        if existing is None and cleaned.isascii():
            existing = query.filter(func.lower(CharacterCore.name) == cleaned.lower()).first()
        if existing:
            profile = self.get_active_profile(existing.id)
            manifest = profile.manifest if profile and isinstance(profile.manifest, dict) else None
            return _augment_core_with_manifest(existing, manifest), False

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entity_id = f"character-{cleaned[:200]}"
        manifest = empty_manifest_dict()
        meta = manifest.setdefault("_meta", {})
        identity = manifest.setdefault("_identity", {})
        meta["character_name"] = cleaned
        meta["entity_id"] = entity_id
        meta["created_at"] = now
        meta["updated_at"] = now
        if tags:
            meta["tags"] = list(tags)
        if notes:
            meta["notes"] = notes
        identity["name"] = cleaned
        identity["entity_id"] = entity_id
        identity["age_appearance"] = str(base_age)
        if gender_spectrum is not None:
            identity["gender_spectrum"] = gender_spectrum

        core = CharacterCore(
            uuid=uuid4(),
            name=cleaned,
            base_age=base_age,
            gender_spectrum=gender_spectrum,
            identity_anchor={},
            tags=list(tags or []),
            meta_info={"notes": notes} if notes else {},
        )
        self.db.add(core)
        self.db.flush()
        profile = CharacterProfile(
            core_id=core.id,
            version=1,
            is_active=True,
            manifest=manifest,
        )
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(core)
        return _augment_core_with_manifest(core, manifest), True
    
    def get_active_profile(self, core_id: int) -> Optional[CharacterProfile]:
        """
        取得角色的啟用中 Profile
        
        Args:
            core_id: 角色核心 ID
        
        Returns:
            CharacterProfile or None
        """
        profile = self.db.query(CharacterProfile).filter(
            CharacterProfile.core_id == core_id,
            CharacterProfile.is_active == True
        ).order_by(CharacterProfile.version.desc()).first()
        
        return profile
    
    def get_profile_version(self, core_id: int, version: int) -> Optional[CharacterProfile]:
        """
        取得特定版本的 Profile
        
        Args:
            core_id: 角色核心 ID
            version: 版本號
        
        Returns:
            CharacterProfile or None
        """
        profile = self.db.query(CharacterProfile).filter(
            CharacterProfile.core_id == core_id,
            CharacterProfile.version == version
        ).first()
        
        return profile

    def get_or_create_active_profile(self, core_id: int) -> CharacterProfile:
        """取得啟用 profile；若不存在則建立 version=1 空白 profile。"""
        profile = self.get_active_profile(core_id)
        if profile:
            return profile

        profile = CharacterProfile(
            core_id=core_id,
            version=1,
            is_active=True,
            manifest={},
        )
        self.db.add(profile)
        self.db.flush()
        return profile

    def get_editor_payload(self, character_id: int) -> CharacterEditorResponse:
        """給 GUI 讀取完整角色編輯資料。"""
        full = self.get_character_by_id(character_id)
        profile = self.get_or_create_active_profile(character_id)
        if not full.profile:
            full = self.get_character_by_id(character_id)
        return CharacterEditorResponse(
            core=full.core,
            profile=CharacterProfileResponse.model_validate(profile),
        )

    def save_charpass(
        self,
        character_id: int,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        core = self.db.query(CharacterCore).filter(CharacterCore.id == character_id).first()
        if not core:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character with id {character_id} not found",
            )

        profile = self.get_or_create_active_profile(character_id)
        payload = dict(manifest or {})
        meta = payload.setdefault("_meta", {})
        identity = payload.setdefault("_identity", {})
        meta.setdefault("character_name", identity.get("name") or core.name)
        meta["updated_at"] = core.updated_at.isoformat() if core.updated_at else meta.get("updated_at")
        identity.setdefault("name", core.name)
        profile.manifest = payload
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(profile)
        return profile.manifest or {}

    def get_version_summary(self, character_id: int) -> dict[str, Any]:
        full = self.get_character_by_id(character_id)
        profile = full.profile
        manifest = profile.manifest if profile and isinstance(profile.manifest, dict) else {}
        meta = manifest.get("_meta") if isinstance(manifest.get("_meta"), dict) else {}
        identity = manifest.get("_identity") if isinstance(manifest.get("_identity"), dict) else {}
        entity_id = str(meta.get("entity_id") or identity.get("entity_id") or full.core.codename or f"character-{full.core.name}").strip()
        variants = self.db.query(CharacterVariant).filter(
            CharacterVariant.core_id == character_id
        ).order_by(CharacterVariant.created_at.desc()).limit(100).all()
        branches = []
        for item in variants:
            result_metadata = item.result_metadata if isinstance(item.result_metadata, dict) else {}
            image_generation = (
                result_metadata.get("image_generation")
                if isinstance(result_metadata.get("image_generation"), dict)
                else {}
            )
            images = _summary_images_from_payload(image_generation, result_metadata)
            summary = _branch_summary(
                images,
                kind="variant",
                branch_id=str(item.id),
                purpose=image_generation.get("purpose"),
                status=item.status,
                review_status=result_metadata.get("review_status"),
                updated_at=item.updated_at.isoformat() if item.updated_at else None,
            )
            result_path = (
                summary.get("hero_asset_path")
                or summary.get("thumbnail_asset_path")
                or result_metadata.get("face_detail_asset_path")
                or result_metadata.get("thumbnail_asset_path")
                or (summary.get("asset_paths") or [None])[0]
            )
            branches.append(
                {
                    "kind": "variant",
                    "branch_id": str(item.id),
                    "label": f"variant/{item.id}",
                    "purpose": image_generation.get("purpose"),
                    "provider": image_generation.get("provider"),
                    "model": image_generation.get("model"),
                    "review": image_generation.get("review") or {},
                    "prompt": image_generation.get("prompt"),
                    "negative_prompt": image_generation.get("negative_prompt"),
                    "evolution_params": result_metadata.get("evolution_params") or item.evolution_params or {},
                    "request": result_metadata.get("image_request") or {},
                    "response": {
                        "provider": image_generation.get("provider"),
                        "model": image_generation.get("model"),
                        "images": image_generation.get("images") or [],
                        "images_by_angle": image_generation.get("images_by_angle") or {},
                        "review": image_generation.get("review") or {},
                    },
                    **summary,
                    "result_url": (
                        f"/api/v1/characters/{character_id}/assets/{result_path}"
                        if isinstance(result_path, str) and result_path.strip()
                        else item.result_url
                    ),
                }
            )
        if entity_id:
            branches.extend(_image_job_branches(entity_id, character_id))
        existing_ids = {str(item.get("branch_id") or "") for item in branches}
        for branch in _latest_image_branches(manifest, character_id):
            if str(branch.get("branch_id") or "") in existing_ids:
                continue
            branches.append(branch)
        branches = _dedupe_branches(branches)
        branches.sort(key=_branch_sort_tuple)
        for index, branch in enumerate(branches):
            branch["sort_order"] = index
            strip_final_asset_path_from_branch(branch)
        return {
            "entity_id": entity_id,
            "current_path": "database:active_profile",
            "history": [
                {
                    "name": f"profile-v{profile.version}" if profile else "profile-v1",
                    "path": "database:active_profile",
                    "kind": "current",
                    "is_binary": False,
                }
            ],
            "branches": branches,
        }

    def get_age_gallery(
        self,
        character_id: int,
        *,
        age_start: int = 1,
        age_end: int = 80,
    ) -> dict[str, Any]:
        """依歲數列出面部／T 型資產路徑，供點選預覽。"""
        from characteros.services.age_gallery import build_age_gallery

        full = self.get_character_by_id(character_id)
        profile = full.profile
        manifest = profile.manifest if profile and isinstance(profile.manifest, dict) else {}
        meta = manifest.get("_meta") if isinstance(manifest.get("_meta"), dict) else {}
        identity = manifest.get("_identity") if isinstance(manifest.get("_identity"), dict) else {}
        entity_id = str(
            meta.get("entity_id")
            or identity.get("entity_id")
            or full.core.codename
            or f"character-{full.core.name}"
        ).strip()
        folder = CharpassStore().entity_dir(entity_id)
        return build_age_gallery(
            folder,
            character_id=character_id,
            character_name=full.core.name if full and full.core else None,
            age_start=age_start,
            age_end=age_end,
        )

    def update_character_editor(
        self,
        character_id: int,
        body: CharacterEditorUpdateRequest,
    ) -> CharacterEditorResponse:
        """更新 core + active profile，供完整角色編輯器使用。"""
        core = self.db.query(CharacterCore).filter(CharacterCore.id == character_id).first()
        if not core:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character with id {character_id} not found",
            )

        profile = self.get_or_create_active_profile(character_id)

        # core fields
        core.name = body.name
        core.codename = body.codename
        core.gender_spectrum = body.gender_spectrum
        core.base_age = body.base_age
        core.identity_anchor = body.identity_anchor or {}
        core.tags = body.tags or []
        core.meta_info = body.metadata or {}

        # profile fields — 內容變更時遞增版本號，確保 variant_hash 不會與舊快取衝突
        import hashlib, json
        old_manifest_hash = hashlib.sha256(
            json.dumps(profile.manifest or {}, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        new_manifest_hash = hashlib.sha256(
            json.dumps(body.manifest or {}, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        if old_manifest_hash != new_manifest_hash:
            profile.version = (profile.version or 1) + 1

        profile.project_name = body.project_name
        profile.project_id = body.project_id
        profile.style_preset = body.style_preset
        profile.outfit_config = body.outfit_config or {}
        profile.created_by = body.created_by
        profile.notes = body.notes
        profile.manifest = body.manifest or {}

        # 讓 style_preset 直接映射到 manifest：供 imaging 依 `_style.character_style.visual.*` 組 prompt
        if profile.manifest is None or not isinstance(profile.manifest, dict):
            profile.manifest = {}

        if body.style_preset:
            raw = str(body.style_preset).replace("，", ",")
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            visual = (
                profile.manifest.setdefault("_style", {})
                .setdefault("character_style", {})
                .setdefault("visual", {})
            )
            if isinstance(visual, dict):
                if len(parts) >= 1 and not visual.get("medium"):
                    visual["medium"] = parts[0]
                if len(parts) >= 2 and not visual.get("aesthetic"):
                    visual["aesthetic"] = ", ".join(parts[1:])

        # 讓 created_by 也寫進 manifest meta，避免 UI/檢視落差
        if body.created_by is not None:
            meta = profile.manifest.setdefault("_meta", {})
            if isinstance(meta, dict):
                meta["created_by"] = body.created_by

        profile.is_active = True

        self.db.add(core)
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(core)
        self.db.refresh(profile)

        return CharacterEditorResponse(
            core=CharacterCoreResponse.model_validate(core),
            profile=CharacterProfileResponse.model_validate(profile),
        )
