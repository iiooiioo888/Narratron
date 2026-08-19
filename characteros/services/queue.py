"""CharacterOS 變體佇列：檢查、寫入、冪等；Sprint 1 只寫 pending。"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import logging

from characteros.imaging.settings import settings as imaging_settings
from characteros.models.orm import CharacterCore, CharacterProfile, CharacterVariant
from characteros.services.characters import CharacterService
from characteros.services.imaging import (
    ImagingService,
    finalize_reviewed_generation,
    sync_review_artifacts,
)
from characteros.services.variant_processor import (
    evolve_manifest,
    extract_image_request,
    sanitize_evolution_params,
)
from characteros.utils.hash import compute_variant_hash

logger = logging.getLogger(__name__)
PREFERRED_RESULT_ANGLES = (
    "face_detail",
    "front",
    "three_quarter",
    "left",
    "right",
    "back",
    "top",
    "bottom",
)


def _entity_id_for_manifest(
    manifest: dict[str, Any],
    fallback_name: str,
) -> str:
    meta = manifest.get("_meta") if isinstance(manifest.get("_meta"), dict) else {}
    identity = manifest.get("_identity") if isinstance(manifest.get("_identity"), dict) else {}
    raw = str(meta.get("entity_id") or identity.get("entity_id") or "").strip()
    if raw:
        return raw
    fallback = str(fallback_name or "character").strip() or "character"
    return f"character-{fallback}"


def _prepare_result_urls(
    core_id: int,
    payload: dict[str, Any],
    *,
    processed_at: str,
) -> tuple[str, dict[str, Any]]:
    images = payload.get("images") if isinstance(payload.get("images"), list) else []
    image_urls: list[str] = []
    representative_url: str | None = None
    for image in images:
        if not isinstance(image, dict):
            continue
        asset_path = str(image.get("asset_path") or "").strip()
        if asset_path:
            image_url = f"/api/v1/characters/{core_id}/assets/{asset_path}"
            image_urls.append(image_url)
            if representative_url is None:
                representative_url = image_url

    thumbnail_image = payload.get("thumbnail_image") if isinstance(payload.get("thumbnail_image"), dict) else {}
    thumbnail_asset_path = str(thumbnail_image.get("asset_path") or "").strip()
    if thumbnail_asset_path:
        representative_url = f"/api/v1/characters/{core_id}/assets/{thumbnail_asset_path}"
    else:
        for angle in PREFERRED_RESULT_ANGLES:
            for image in images:
                if not isinstance(image, dict):
                    continue
                if str(image.get("angle") or "").strip() != angle:
                    continue
                asset_path = str(image.get("asset_path") or "").strip()
                if asset_path:
                    representative_url = f"/api/v1/characters/{core_id}/assets/{asset_path}"
                    break
            if representative_url:
                break
    result_url = representative_url or (image_urls[0] if image_urls else f"/api/v1/characters/{core_id}/variants")
    metadata = {
        "processed_at": processed_at,
        "thumbnail_asset_path": thumbnail_asset_path or None,
        "face_detail_asset_path": payload.get("face_detail_asset_path"),
        "face_detail_count": payload.get("face_detail_count") or 0,
        "image_generation": {
            "provider": payload.get("provider"),
            "model": payload.get("model"),
            "purpose": payload.get("purpose"),
            "prompt": payload.get("prompt"),
            "negative_prompt": payload.get("negative_prompt"),
            "multi_angle": payload.get("multi_angle"),
            "angles": payload.get("angles") or [],
            "images": images,
            "image_urls": image_urls,
            "images_by_angle": payload.get("images_by_angle") or {},
            "face_detail_images": payload.get("face_detail_images") or [],
            "face_detail_asset_path": payload.get("face_detail_asset_path"),
            "face_detail_count": payload.get("face_detail_count") or 0,
            "thumbnail_image": payload.get("thumbnail_image"),
            "thumbnail_asset_path": thumbnail_asset_path or None,
            "review": payload.get("review") or {},
        },
    }
    return result_url, metadata


class QueueManager:
    """
    佇列管理器：處理變體生成請求的冪等性與佇列寫入
    
    核心邏輯：
    1. 計算 variant_hash
    2. 檢查是否已存在（無論 status）
    3. 若存在且 ready → 直接回傳
    4. 若存在且 pending → 回傳現有 queue_id（避免重複）
    5. 若不存在 → 寫入新記錄（status='pending'）
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def request_variant_generation(
        self,
        core_id: int,
        evolution_params: Dict[str, Any],
        priority: int = 0
    ) -> Tuple[CharacterVariant, bool]:
        """
        請求變體生成
        
        Args:
            core_id: 角色核心 ID
            evolution_params: 演化參數
            priority: 優先級 (0-10)
        
        Returns:
            Tuple[CharacterVariant, is_new]
            - CharacterVariant: 變體記錄（現有的或新建的）
            - is_new: True 如果是新建的，False 如果是現有的
        
        Raises:
            HTTPException 404 if core not found
        """
        # 1. 驗證 core 存在
        core = self.db.query(CharacterCore).filter(CharacterCore.id == core_id).first()
        if not core:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character core {core_id} not found"
            )
        
        # 2. 取得 active profile 的版本號（用於 hash 計算）
        active_profile = self.db.query(CharacterProfile).filter(
            CharacterProfile.core_id == core_id,
            CharacterProfile.is_active == True
        ).order_by(CharacterProfile.version.desc()).first()
        
        profile_version = active_profile.version if active_profile else 1
        profile_id = active_profile.id if active_profile else None
        
        # 3. 計算 variant_hash
        variant_hash = compute_variant_hash(core_id, profile_version, evolution_params)
        
        # 4. 檢查是否已存在
        existing_variant = self.db.query(CharacterVariant).filter(
            CharacterVariant.core_id == core_id,
            CharacterVariant.variant_hash == variant_hash
        ).first()
        
        if existing_variant:
            # 已存在，直接回傳（無論 status 是 pending/ready/failed）
            logger.info(
                f"Variant already exists: core_id={core_id}, hash={variant_hash[:16]}..., "
                f"status={existing_variant.status}"
            )
            return existing_variant, False
        
        # 5. 不存在，創建新記錄（status='pending'）
        new_variant = CharacterVariant(
            core_id=core_id,
            profile_id=profile_id,
            variant_hash=variant_hash,
            evolution_params=evolution_params,
            status='pending',
            priority=priority,
            retry_count=0,
            max_retries=3
        )
        
        try:
            self.db.add(new_variant)
            self.db.commit()
            self.db.refresh(new_variant)
            
            logger.info(
                f"New variant queued: id={new_variant.id}, "
                f"core_id={core_id}, hash={variant_hash[:16]}..."
            )
            
            return new_variant, True
            
        except IntegrityError as e:
            # 競爭條件：另一個請求同時寫入了相同的 hash
            # 回滾並重新查詢
            self.db.rollback()
            logger.warning(f"IntegrityError on variant insert, re-querying: {e}")
            
            existing_variant = self.db.query(CharacterVariant).filter(
                CharacterVariant.core_id == core_id,
                CharacterVariant.variant_hash == variant_hash
            ).first()
            
            if existing_variant:
                return existing_variant, False
            else:
                # 極端情況：仍然找不到，可能是其他錯誤
                raise
    
    def get_variant_by_id(self, variant_id: int) -> Optional[CharacterVariant]:
        """
        透過 ID 取得變體記錄
        
        Args:
            variant_id: 變體 ID
        
        Returns:
            CharacterVariant or None
        """
        return self.db.query(CharacterVariant).filter(
            CharacterVariant.id == variant_id
        ).first()

    def process_variant(self, variant_id: int) -> CharacterVariant:
        """處理單一 pending/failed 變體任務並標記 ready/failed。"""
        variant = self.get_variant_by_id(variant_id)
        if not variant:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Queue task {variant_id} not found",
            )
        if variant.status == "ready":
            return variant

        started_at = datetime.now(timezone.utc)
        try:
            profile = None
            if variant.profile_id:
                profile = self.db.query(CharacterProfile).filter(
                    CharacterProfile.id == variant.profile_id
                ).first()
            if profile is None:
                profile = self.db.query(CharacterProfile).filter(
                    CharacterProfile.core_id == variant.core_id,
                    CharacterProfile.is_active == True,
                ).order_by(CharacterProfile.version.desc()).first()

            base_manifest = profile.manifest if profile and isinstance(profile.manifest, dict) else {}
            raw_params = variant.evolution_params or {}
            params = sanitize_evolution_params(raw_params)
            image_request = extract_image_request(raw_params)
            evolved_manifest = evolve_manifest(base_manifest, params)
            finished_at = datetime.now(timezone.utc)

            variant.status = "ready"
            variant.error_message = None
            variant.queue_wait_ms = max(
                0,
                int((started_at - (variant.created_at or started_at)).total_seconds() * 1000),
            )
            variant.generation_duration_ms = max(
                0,
                int((finished_at - started_at).total_seconds() * 1000),
            )
            result_url = f"/api/v1/characters/{variant.core_id}/variants"
            result_metadata = {
                "processed_at": finished_at.isoformat(),
                "evolved_manifest": evolved_manifest,
                "evolution_params": params,
            }
            if image_request:
                core = self.db.query(CharacterCore).filter(CharacterCore.id == variant.core_id).first()
                core_name = core.name if core else f"character-{variant.core_id}"
                persist_enabled = bool(image_request.get("persist", True))
                persist_entity_id = (
                    _entity_id_for_manifest(evolved_manifest, core_name)
                    if persist_enabled
                    else None
                )
                payload = ImagingService().generate_for_manifest(
                    evolved_manifest,
                    purpose=str(image_request.get("purpose") or "identity"),
                    provider_name=str(image_request.get("provider") or imaging_settings.get_provider() or "null"),
                    extra=str(image_request.get("extra") or ""),
                    n=int(image_request.get("n") or 1),
                    model=str(image_request.get("model") or imaging_settings.get_model() or ""),
                    base_url=str(image_request.get("base_url") or imaging_settings.get_base_url() or ""),
                    api_key=str(image_request.get("api_key") or imaging_settings.get_api_key() or ""),
                    persist_entity_id=persist_entity_id,
                    multi_angle=bool(image_request.get("multi_angle", True)),
                    auto_accept=False,
                )
                result_url, image_metadata = _prepare_result_urls(
                    variant.core_id,
                    payload,
                    processed_at=finished_at.isoformat(),
                )
                result_metadata.update(image_metadata)
                result_metadata["persist_entity_id"] = persist_entity_id
                result_metadata["review_status"] = (
                    (payload.get("review") or {}).get("status")
                    if isinstance(payload.get("review"), dict)
                    else None
                )
                result_metadata["image_request"] = image_request

            variant.result_url = result_url
            variant.result_metadata = result_metadata
            self.db.add(variant)
            self.db.commit()
            self.db.refresh(variant)
            return variant
        except Exception as exc:
            variant.status = "failed"
            variant.retry_count = int(variant.retry_count or 0) + 1
            variant.error_message = str(exc)
            self.db.add(variant)
            self.db.commit()
            self.db.refresh(variant)
            return variant

    def review_variant(self, variant_id: int, *, accepted: bool) -> CharacterVariant:
        """人工接受或拒絕已完成的生圖任務。"""
        variant = self.get_variant_by_id(variant_id)
        if not variant:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Queue task {variant_id} not found",
            )
        if variant.status != "ready":
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only ready tasks can be reviewed",
            )

        result_metadata = variant.result_metadata if isinstance(variant.result_metadata, dict) else {}
        image_generation = result_metadata.get("image_generation")
        if not isinstance(image_generation, dict):
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This task has no image generation result to review",
            )

        review = image_generation.get("review") if isinstance(image_generation.get("review"), dict) else {}
        current_status = str(review.get("status") or "").strip() or "pending"
        if current_status == "accepted" and accepted:
            return variant
        if current_status == "accepted" and not accepted:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Accepted tasks cannot be rejected after publish",
            )
        if current_status == "rejected" and not accepted:
            return variant

        if accepted:
            entity_id = str(result_metadata.get("persist_entity_id") or review.get("entity_id") or "").strip()
            if not entity_id:
                from fastapi import HTTPException, status

                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This task has no staged assets to accept",
                )
            promoted = finalize_reviewed_generation(entity_id, image_generation)
            CharacterService(self.db).save_charpass(variant.core_id, promoted["manifest"])
            image_generation.update(promoted["payload"])
            result_metadata["image_generation"] = image_generation
            variant.result_url, image_meta = _prepare_result_urls(
                variant.core_id,
                image_generation,
                processed_at=datetime.now(timezone.utc).isoformat(),
            )
            result_metadata.update(image_meta)
        else:
            review["status"] = "rejected"
            review["rejected_at"] = datetime.now(timezone.utc).isoformat()
            image_generation["review"] = review
            result_metadata["image_generation"] = image_generation
        entity_id = str(result_metadata.get("persist_entity_id") or review.get("entity_id") or "").strip()
        if entity_id:
            sync_review_artifacts(entity_id, image_generation)

        result_metadata["review_status"] = image_generation.get("review", {}).get("status")
        variant.result_metadata = result_metadata
        self.db.add(variant)
        self.db.commit()
        self.db.refresh(variant)
        return variant

    def process_next_pending(self) -> Optional[CharacterVariant]:
        """處理優先級最高且最早建立的 pending 任務。"""
        variant = (
            self.db.query(CharacterVariant)
            .filter(CharacterVariant.status == "pending")
            .order_by(CharacterVariant.priority.desc(), CharacterVariant.created_at.asc())
            .first()
        )
        if not variant:
            return None
        return self.process_variant(variant.id)

    def process_all_pending(self, *, limit: int = 20) -> list[CharacterVariant]:
        """批次處理 pending 任務。"""
        variants = (
            self.db.query(CharacterVariant)
            .filter(CharacterVariant.status == "pending")
            .order_by(CharacterVariant.priority.desc(), CharacterVariant.created_at.asc())
            .limit(max(1, min(limit, 200)))
            .all()
        )
        return [self.process_variant(variant.id) for variant in variants]
    
    def get_pending_queue_count(self) -> int:
        """
        取得待處理佇列數量
        
        Returns:
            int: pending 狀態的變體數量
        """
        return self.db.query(CharacterVariant).filter(
            CharacterVariant.status == 'pending'
        ).count()
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """
        取得佇列統計資訊
        
        Returns:
            Dict with stats
        """
        from sqlalchemy import func
        
        # 各狀態數量
        pending_count = self.db.query(CharacterVariant).filter(
            CharacterVariant.status == 'pending'
        ).count()
        
        ready_count = self.db.query(CharacterVariant).filter(
            CharacterVariant.status == 'ready'
        ).count()
        
        failed_count = self.db.query(CharacterVariant).filter(
            CharacterVariant.status == 'failed'
        ).count()
        
        # 平均等待時間（僅計算有 queue_wait_ms 的記錄）
        avg_wait = self.db.query(func.avg(CharacterVariant.queue_wait_ms)).filter(
            CharacterVariant.queue_wait_ms != None
        ).scalar() or 0.0
        
        # 最老的 pending 記錄
        oldest_pending = self.db.query(CharacterVariant).filter(
            CharacterVariant.status == 'pending'
        ).order_by(CharacterVariant.created_at.asc()).first()
        
        oldest_age_seconds = 0.0
        if oldest_pending:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            created = oldest_pending.created_at.replace(tzinfo=timezone.utc)
            oldest_age_seconds = (now - created).total_seconds()
        
        return {
            "total_pending": pending_count,
            "total_ready": ready_count,
            "total_failed": failed_count,
            "average_wait_time_ms": float(avg_wait),
            "oldest_pending_age_seconds": oldest_age_seconds
        }

    def list_tasks(
        self,
        *,
        status: str | None = None,
        core_id: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """列出佇列任務（含角色名稱），供管理面板使用。"""
        query = (
            self.db.query(CharacterVariant, CharacterCore.name)
            .join(CharacterCore, CharacterCore.id == CharacterVariant.core_id)
        )
        if status:
            query = query.filter(CharacterVariant.status == status)
        if core_id is not None:
            query = query.filter(CharacterVariant.core_id == core_id)
        rows = (
            query.order_by(
                CharacterVariant.priority.desc(),
                CharacterVariant.created_at.asc(),
            )
            .limit(max(1, min(limit, 200)))
            .all()
        )
        tasks: list[dict] = []
        for variant, character_name in rows:
            item = variant.to_dict()
            item["character_name"] = character_name
            tasks.append(item)
        return tasks
