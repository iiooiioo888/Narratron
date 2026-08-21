"""CharacterOS 變體佇列：檢查、寫入、冪等；Sprint 1 只寫 pending。"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import logging

from characteros.models.orm import CharacterCore, CharacterProfile, CharacterVariant
from characteros.services.characters import CharacterService
from characteros.services.age_span import find_next_runnable_task
from characteros.services.pipeline_coordinator import (
    after_image_task_succeeded,
    sync_age_span_task_states,
)
from characteros.services.image_task_runner import (
    ImageQueueExecution,
    execute_image_queue_task,
)
from characteros.services.queue_task_utils import (
    apply_review_metadata,
    build_image_result_metadata,
    effective_task_status,
    review_status_from_metadata,
)
from characteros.services.imaging import finalize_reviewed_generation, sync_review_artifacts
from characteros.services.variant_processor import (
    evolve_manifest,
    extract_image_request,
    sanitize_evolution_params,
)
from characteros.utils.hash import compute_variant_hash
from characteros.services.evolution import EvolutionEngine

logger = logging.getLogger(__name__)


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
        priority: int = 0,
        status: str = "pending",
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
        
        # 2. 取得 active profile 的版本號與 manifest 內容（用於 hash 計算）
        active_profile = self.db.query(CharacterProfile).filter(
            CharacterProfile.core_id == core_id,
            CharacterProfile.is_active == True
        ).order_by(CharacterProfile.version.desc()).first()
        
        profile_version = active_profile.version if active_profile else 1
        profile_id = active_profile.id if active_profile else None
        manifest_content = active_profile.manifest if active_profile else None
        
        # 3. 計算 variant_hash（含 manifest 內容感知）
        variant_hash = compute_variant_hash(core_id, profile_version, evolution_params, manifest_content)
        
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
            status=str(status or "pending").strip() or "pending",
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
    
    def process_pending_variant(self, variant_id: int) -> Optional[CharacterVariant]:
        """處理 pending 變體：透過 EvolutionEngine 演化並標記為 ready。
        
        應由背景任務呼叫，不阻塞 API 請求。
        """
        variant = self.db.query(CharacterVariant).filter(
            CharacterVariant.id == variant_id,
            CharacterVariant.status == 'pending'
        ).first()
        
        if not variant:
            return None
        
        # 取得 active profile 的 manifest
        profile = self.db.query(CharacterProfile).filter(
            CharacterProfile.core_id == variant.core_id,
            CharacterProfile.is_active == True
        ).order_by(CharacterProfile.version.desc()).first()
        
        if not profile or not profile.manifest:
            variant.status = 'failed'
            variant.error_message = 'No active profile with manifest found'
            self.db.commit()
            return variant
        
        # 透過演化引擎產生 evolved manifest
        try:
            import time
            start = time.monotonic()
            
            engine = EvolutionEngine()
            evolved_manifest = engine.apply_evolution(
                base_manifest=profile.manifest,
                evolution_params=variant.evolution_params
            )
            
            elapsed_ms = int((time.monotonic() - start) * 1000)
            
            variant.status = 'ready'
            variant.result_metadata = {
                'evolved_manifest': evolved_manifest,
                'profile_version': profile.version,
            }
            variant.generation_duration_ms = elapsed_ms
            
        except Exception as exc:
            logger.error(f"Variant {variant_id} evolution failed: {exc}", exc_info=True)
            variant.status = 'failed'
            variant.error_message = str(exc)
            variant.retry_count = (variant.retry_count or 0) + 1
        
        self.db.commit()
        self.db.refresh(variant)
        return variant

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

        from datetime import datetime, timezone

        from characteros.services.age_span import (
            RUNNING_STATUS,
            recover_stale_running_tasks,
        )

        all_tasks = self._all_variant_task_dicts()
        recovered = recover_stale_running_tasks(all_tasks)
        if recovered:
            self._apply_age_span_statuses(all_tasks)
            variant = self.get_variant_by_id(variant_id)
            if not variant:
                from fastapi import HTTPException, status

                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Queue task {variant_id} not found",
                )
        current_status = str(variant.status or "").strip().lower()
        in_flight = [
            item
            for item in all_tasks
            if int(item.get("id") or 0) != int(variant_id)
            and str(item.get("status") or "").strip().lower() == RUNNING_STATUS
        ]
        if in_flight or (current_status != RUNNING_STATUS and any(
            str(item.get("status") or "").strip().lower() == RUNNING_STATUS for item in all_tasks
        )):
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="已有一張圖正在生成，生圖迴圈一次只允許一張",
            )
        if current_status not in {"pending", "failed", RUNNING_STATUS}:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Task {variant_id} is {current_status or 'unknown'}, not runnable",
            )
        if current_status != RUNNING_STATUS:
            variant.status = RUNNING_STATUS
            metadata = dict(variant.result_metadata or {})
            metadata["started_at"] = datetime.now(timezone.utc).isoformat()
            variant.result_metadata = metadata
            self.db.add(variant)
            self.db.commit()
            self.db.refresh(variant)

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
        core = self.db.query(CharacterCore).filter(CharacterCore.id == variant.core_id).first()
        core_name = core.name if core else f"character-{variant.core_id}"
        raw_params = variant.evolution_params or {}
        evolved_for_entity = evolve_manifest(
            base_manifest,
            sanitize_evolution_params(raw_params),
        )
        sibling_tasks = [
            item.to_dict()
            for item in self.db.query(CharacterVariant)
            .filter(CharacterVariant.core_id == variant.core_id)
            .all()
        ]

        outcome = execute_image_queue_task(
            ImageQueueExecution(
                core_id=int(variant.core_id),
                task_id=int(variant.id),
                character_name=str(core_name),
                raw_evolution_params=raw_params,
                sibling_tasks=sibling_tasks,
                base_manifest=base_manifest,
                entity_id=_entity_id_for_manifest(evolved_for_entity, core_name),
                save_manifest=lambda manifest: CharacterService(self.db).save_charpass(variant.core_id, manifest),
                created_at=variant.created_at,
            )
        )

        variant.status = outcome.status
        variant.error_message = outcome.error_message
        variant.queue_wait_ms = outcome.queue_wait_ms
        variant.generation_duration_ms = outcome.generation_duration_ms
        if outcome.result_url:
            variant.result_url = outcome.result_url
        variant.result_metadata = outcome.result_metadata
        if outcome.status == "failed":
            variant.retry_count = int(variant.retry_count or 0) + 1

        self.db.add(variant)
        self.db.commit()
        self.db.refresh(variant)

        if outcome.status == "ready":
            tasks = self._all_variant_task_dicts()
            sync_age_span_task_states(tasks)
            self._apply_age_span_statuses(tasks)

            def _enqueue(**kwargs: Any) -> tuple[CharacterVariant, bool]:
                return self.request_variant_generation(
                    core_id=int(kwargs["core_id"]),
                    evolution_params=kwargs["evolution_params"],
                    priority=int(kwargs.get("priority") or 0),
                    status=str(kwargs.get("status") or "pending"),
                )

            after_image_task_succeeded(
                self._all_variant_task_dicts(),
                enqueue=_enqueue,
                core_id=variant.core_id,
            )
            self._sync_age_span_queue()
        elif outcome.status == "waiting":
            self._sync_age_span_queue()

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
            variant.result_url, image_meta, _image_urls = build_image_result_metadata(
                core_id=variant.core_id,
                payload=image_generation,
                image_request={},
                provider_name=str(image_generation.get("provider") or ""),
                explicit_model=str(image_generation.get("model") or ""),
                persist_entity_id=entity_id or None,
                processed_at=datetime.now(timezone.utc).isoformat(),
            )
            result_metadata.update(image_meta)
        else:
            review["status"] = "rejected"
            review["rejected_at"] = datetime.now(timezone.utc).isoformat()
            image_generation["review"] = review
        entity_id = str(result_metadata.get("persist_entity_id") or review.get("entity_id") or "").strip()
        if entity_id:
            sync_review_artifacts(entity_id, image_generation)

        apply_review_metadata(result_metadata, image_generation)
        result_metadata["effective_status"] = effective_task_status(variant.status, result_metadata)
        variant.result_metadata = result_metadata
        self.db.add(variant)
        self.db.commit()
        self.db.refresh(variant)
        return variant

    def ensure_following_age_span_tasks(self, *, core_id: int | None = None) -> list[CharacterVariant]:
        """年齡軸完成一步後，只再排入下一步。"""
        tasks = self._all_variant_task_dicts()

        def _enqueue(**kwargs: Any) -> tuple[CharacterVariant, bool]:
            variant, is_new = self.request_variant_generation(
                core_id=int(kwargs["core_id"]),
                evolution_params=kwargs["evolution_params"],
                priority=int(kwargs.get("priority") or 0),
                status=str(kwargs.get("status") or "pending"),
            )
            return variant, is_new

        created_variants: list[CharacterVariant] = []
        for item in enqueue_next_age_span_steps(tasks, enqueue=_enqueue, core_id=core_id):
            if isinstance(item, CharacterVariant):
                created_variants.append(item)
        self._sync_age_span_queue()
        return created_variants

    def _apply_age_span_statuses(self, tasks: list[dict[str, Any]]) -> None:
        changed = False
        by_id = {int(item.get("id") or 0): str(item.get("status") or "") for item in tasks}
        for variant in self.db.query(CharacterVariant).all():
            next_status = by_id.get(int(variant.id))
            if next_status in {"pending", "waiting"} and variant.status != next_status:
                variant.status = next_status
                self.db.add(variant)
                changed = True
        if changed:
            self.db.commit()

    def _sync_age_span_queue(self) -> None:
        tasks = self._all_variant_task_dicts()
        sync_age_span_task_states(tasks)
        self._apply_age_span_statuses(tasks)

    def normalize_age_span_statuses(self) -> None:
        self._sync_age_span_queue()

    def _variant_task_dict(self, variant: CharacterVariant) -> dict[str, Any]:
        return {
            "id": variant.id,
            "core_id": variant.core_id,
            "status": variant.status,
            "priority": variant.priority,
            "evolution_params": variant.evolution_params or {},
            "result_metadata": variant.result_metadata or {},
            "created_at": variant.created_at.isoformat() if variant.created_at else "",
        }

    def _list_pending_variant_dicts(self) -> list[dict[str, Any]]:
        variants = (
            self.db.query(CharacterVariant)
            .filter(CharacterVariant.status == "pending")
            .order_by(CharacterVariant.priority.desc(), CharacterVariant.created_at.asc())
            .all()
        )
        return [self._variant_task_dict(variant) for variant in variants]

    def _all_variant_task_dicts(self) -> list[dict[str, Any]]:
        variants = self.db.query(CharacterVariant).all()
        return [self._variant_task_dict(variant) for variant in variants]

    def reset_failed_tasks(
        self,
        *,
        core_id: int | None = None,
        from_id: int | None = None,
    ) -> list[CharacterVariant]:
        """將 failed 任務重設為 pending。"""
        query = self.db.query(CharacterVariant).filter(CharacterVariant.status == "failed")
        if core_id is not None:
            query = query.filter(CharacterVariant.core_id == int(core_id))
        if from_id is not None:
            query = query.filter(CharacterVariant.id >= int(from_id))
        reset: list[CharacterVariant] = []
        for variant in query.all():
            variant.status = "waiting"
            variant.error_message = None
            self.db.add(variant)
            reset.append(variant)
        if reset:
            self.db.commit()
            self._sync_age_span_queue()
            for variant in reset:
                self.db.refresh(variant)
        return reset

    def clear_tasks(self, *, core_id: int | None = None) -> int:
        """清空佇列任務；可選只清除指定角色的任務。"""
        query = self.db.query(CharacterVariant)
        if core_id is not None:
            query = query.filter(CharacterVariant.core_id == int(core_id))
        removed = query.count()
        if removed:
            query.delete(synchronize_session=False)
            self.db.commit()
        return removed

    def reset_variant_to_pending(self, variant_id: int) -> CharacterVariant:
        variant = self.get_variant_by_id(variant_id)
        if not variant:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Queue task {variant_id} not found",
            )
        if variant.status != "failed":
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only failed tasks can be reset to pending",
            )
        variant.status = "waiting"
        variant.error_message = None
        self.db.add(variant)
        self.db.commit()
        self._sync_age_span_queue()
        self.db.refresh(variant)
        return variant

    def process_next_pending(self, *, core_id: int | None = None) -> Optional[CharacterVariant]:
        """處理下一筆可執行的 pending 任務。"""
        tasks = self._all_variant_task_dicts()

        def _enqueue(**kwargs: Any) -> tuple[CharacterVariant, bool]:
            return self.request_variant_generation(
                core_id=int(kwargs["core_id"]),
                evolution_params=kwargs["evolution_params"],
                priority=int(kwargs.get("priority") or 0),
                status=str(kwargs.get("status") or "pending"),
            )

        from characteros.services.pipeline_coordinator import prepare_for_processing

        prepare_for_processing(tasks, enqueue=_enqueue, core_id=core_id)
        self._sync_age_span_queue()
        # nested enqueue 寫入 DB，須重載後才能看到新任務
        tasks = self._all_variant_task_dicts()
        scoped = tasks if core_id is None else [
            item for item in tasks if int(item.get("core_id", 0)) == int(core_id)
        ]
        runnable = find_next_runnable_task(scoped)
        if not runnable:
            return None
        from fastapi import HTTPException, status as http_status

        try:
            return self.process_variant(int(runnable["id"]))
        except HTTPException as exc:
            if exc.status_code == http_status.HTTP_409_CONFLICT:
                return None
            raise

    def process_all_pending(self, *, limit: int = 20) -> list[CharacterVariant]:
        """批次處理 pending 任務（每次只處理當下可執行者）。"""
        processed: list[CharacterVariant] = []
        max_count = max(1, min(limit, 200))
        for _ in range(max_count):
            self._sync_age_span_queue()
            self.ensure_following_age_span_tasks()
            runnable = find_next_runnable_task(self._all_variant_task_dicts())
            if not runnable:
                break
            processed.append(self.process_variant(int(runnable["id"])))
        return processed
    
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
        
        waiting_count = self.db.query(CharacterVariant).filter(
            CharacterVariant.status == 'waiting'
        ).count()
        
        running_count = self.db.query(CharacterVariant).filter(
            CharacterVariant.status == 'running'
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
            created_at = oldest_pending.created_at
            # 正確處理時區：如果已是 aware datetime 則直接用，否則補 UTC
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            oldest_age_seconds = (now - created_at).total_seconds()
        
        return {
            "total_pending": pending_count,
            "total_waiting": waiting_count,
            "total_running": running_count,
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
            .limit(max(1, min(limit, 400)))
            .all()
        )
        tasks: list[dict] = []
        for variant, character_name in rows:
            item = variant.to_dict()
            item["character_name"] = character_name
            result_metadata = item.get("result_metadata") if isinstance(item.get("result_metadata"), dict) else {}
            item["review_status"] = review_status_from_metadata(result_metadata)
            item["effective_status"] = effective_task_status(item.get("status"), result_metadata)
            tasks.append(item)
        return tasks
