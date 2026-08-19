"""CharacterOS 角色查詢服務。"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
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
from narratron.charpass.store import CharpassStore

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

ANGLE_HINTS = {
    "face_detail": ("face_detail", "face-detail", "face detail"),
}

KNOWN_ANGLES = tuple(ANGLE_SORT_ORDER.keys())


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


def _sort_images(images: Any) -> list[dict[str, Any]]:
    if not isinstance(images, list):
        return []
    items = [dict(item) for item in images if isinstance(item, dict)]
    for item in items:
        normalized_angle = _image_angle_value(item)
        if normalized_angle:
            item["angle"] = normalized_angle
    items.sort(
        key=lambda item: (
            ANGLE_SORT_ORDER.get(_image_angle_value(item), 999),
            str(item.get("filename") or item.get("final_asset_path") or ""),
            str(item.get("asset_path") or item.get("final_asset_path") or ""),
        )
    )
    return items


def _images_by_angle_summary(images: Any) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in _sort_images(images):
        angle = _image_angle_value(item) or "unclassified"
        item["angle"] = angle
        grouped.setdefault(angle, []).append(item)
    return grouped


def _normalize_angle(value: Any) -> str:
    raw = str(value or "").strip()
    return raw if raw else ""


def _infer_angle_from_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip().lower()
        if not text:
            continue
        for angle, hints in ANGLE_HINTS.items():
            if any(hint in text for hint in hints):
                return angle
        for angle in KNOWN_ANGLES:
            normalized = angle.replace("_", " ")
            if f"[{angle}]" in text or angle in text or normalized in text:
                return angle
    return ""


def _infer_angle_from_prompt(prompt: Any) -> str:
    text = str(prompt or "").strip().lower()
    if not text:
        return ""
    for angle in KNOWN_ANGLES:
        if f"[{angle}]" in text:
            return angle
    return ""


def _image_angle_value(image: dict[str, Any]) -> str:
    if not isinstance(image, dict):
        return ""
    explicit = _normalize_angle(image.get("angle"))
    if explicit:
        return explicit
    requested_angle = _normalize_angle(image.get("requested_angle"))
    if requested_angle:
        return requested_angle
    prompt_angle = _infer_angle_from_prompt(image.get("prompt"))
    if prompt_angle:
        return prompt_angle
    purpose = str(image.get("purpose") or image.get("requested_purpose") or "").strip()
    if purpose == "face_detail":
        return "face_detail"
    return _infer_angle_from_text(
        image.get("final_asset_path"),
        image.get("asset_path"),
        image.get("filename"),
        image.get("note"),
        image.get("prompt"),
        image.get("uri"),
        image.get("url"),
    )


def _summary_images_from_payload(
    image_generation: dict[str, Any],
    result_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    images = image_generation.get("images")
    if isinstance(images, list) and images:
        return images

    flattened: list[dict[str, Any]] = []
    images_by_angle = image_generation.get("images_by_angle")
    if isinstance(images_by_angle, dict):
        for angle, entries in images_by_angle.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                normalized = dict(entry)
                normalized.setdefault("angle", str(angle))
                normalized.setdefault(
                    "filename",
                    normalized.get("asset_path") or normalized.get("final_asset_path") or str(angle),
                )
                flattened.append(normalized)
    if flattened:
        return flattened

    fallback_images: list[dict[str, Any]] = []
    for source in (
        image_generation.get("face_detail_images"),
        [image_generation.get("thumbnail_image")],
    ):
        if not isinstance(source, list):
            continue
        for entry in source:
            if not isinstance(entry, dict):
                continue
            normalized = dict(entry)
            normalized.setdefault("angle", _image_angle_value(normalized) or "unclassified")
            normalized.setdefault(
                "filename",
                normalized.get("asset_path") or normalized.get("final_asset_path") or normalized.get("angle") or "image",
            )
            fallback_images.append(normalized)

    for angle, asset_path in (
        ("face_detail", result_metadata.get("face_detail_asset_path")),
        ("front", result_metadata.get("thumbnail_asset_path")),
    ):
        path = str(asset_path or "").strip()
        if not path:
            continue
        fallback_images.append(
            {
                "angle": angle,
                "asset_path": path,
                "filename": path,
            }
        )
    return fallback_images


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
    # `branches` 會以 reverse=True 排序，因此數值越大代表越前面。
    sort_priority = 2 if str(purpose or "").strip() == "face_detail" else 1 if has_face_detail else 0
    status_summary = effective_status or normalized_status
    face_detail_summary = f"face_detail x{len(face_detail_images)}" if face_detail_images else ""
    hero_asset_path = (
        str(face_detail_images[0].get("asset_path") or "").strip()
        if face_detail_images
        else thumbnail_asset_path
    )
    representative_angle = "face_detail" if face_detail_images else (angles[0] if angles else None)
    review_label = normalized_review_status or normalized_status
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
        "face_detail_summary": face_detail_summary,
        "image_count": image_count,
        "purpose_summary": purpose_summary,
        "hero_asset_path": hero_asset_path or None,
        "representative_asset_path": hero_asset_path or None,
        "representative_angle": representative_angle,
        "review_label": review_label,
        "sort_priority": sort_priority,
        "summary_fields": {
            "status": status_summary,
            "review_status": normalized_review_status,
            "effective_status": effective_status,
            "purpose": purpose_summary,
            "angles": angles,
            "angles_summary": angles_summary,
            "image_count": image_count,
            "has_face_detail": has_face_detail,
            "face_detail_count": len(face_detail_images),
            "thumbnail_asset_path": thumbnail_asset_path,
            "face_detail_asset_path": (
                str(face_detail_images[0].get("asset_path") or "").strip() if face_detail_images else None
            ),
            "hero_asset_path": hero_asset_path or None,
            "representative_asset_path": hero_asset_path or None,
            "representative_angle": representative_angle,
            "review_label": review_label,
            "sort_priority": sort_priority,
        },
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


def _branch_quality_score(branch: dict[str, Any]) -> tuple[int, int, int]:
    images_by_angle = branch.get("images_by_angle") if isinstance(branch.get("images_by_angle"), dict) else {}
    return (
        _review_rank(branch.get("effective_status") or branch.get("review_status") or branch.get("status")),
        len(branch.get("asset_paths") or []),
        len(images_by_angle),
    )


def _review_rank(value: Any) -> int:
    normalized = str(value or "").strip().lower()
    if normalized == "pending":
        return 0
    if normalized == "ready":
        return 1
    if normalized == "accepted":
        return 2
    if normalized == "rejected":
        return 3
    if normalized == "failed":
        return 4
    return 5


def _branch_visual_rank(branch: dict[str, Any]) -> int:
    purpose = str(branch.get("purpose") or branch.get("purpose_summary") or "").strip()
    if purpose == "face_detail":
        return 0
    angles = branch.get("angles") if isinstance(branch.get("angles"), list) else []
    if "face_detail" in [str(item).strip() for item in angles]:
        return 1
    if branch.get("representative_asset_path") or branch.get("thumbnail_asset_path"):
        return 2
    return 3


def _updated_sort_value(value: Any) -> float:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    if isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _branch_sort_tuple(branch: dict[str, Any]) -> tuple[int, int, float, str, str]:
    return (
        _branch_visual_rank(branch),
        _review_rank(branch.get("effective_status") or branch.get("review_status") or branch.get("status")),
        -_updated_sort_value(branch.get("updated_at")),
        str(branch.get("kind") or ""),
        str(branch.get("branch_id") or ""),
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
            joinedload(CharacterCore.profiles).and_(CharacterProfile.is_active == True)
        ).filter(CharacterCore.id == character_id).first()
        
        if not core:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character with id {character_id} not found"
            )
        
        # 取得 active profile（可能有多個版本，只取最新啟用的）
        active_profile = None
        if core.profiles:
            # 按版本號降序排列，取第一個
            active_profile = sorted(
                [p for p in core.profiles if p.is_active],
                key=lambda x: x.version,
                reverse=True
            )[0] if any(p.is_active for p in core.profiles) else None
        
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

        # profile fields
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
