"""CharacterOS 管理路由：佇列統計與系統指標。"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from characteros.imaging.settings import settings
from characteros.models.database import get_db
from characteros.models.schema import (
    AgeSpanPipelineStatusResponse,
    ImagingConfigResponse,
    ImagingConfigUpdateRequest,
    QueueStatsResponse,
    QueueTaskItem,
    QueueTaskListResponse,
    QueueWorkerStatusResponse,
    SystemMetricsResponse,
)
from characteros.services.queue_worker import (
    resume_and_wake_queue_worker,
    set_worker_paused,
    worker_status,
)
from characteros.services.age_span import summarize_age_span_pipeline
from characteros.services.branch_summary import strip_final_asset_path_from_image_generation
from characteros.services.queue import QueueManager
from characteros.storage.db_availability import (
    is_database_available,
    mark_database_unavailable,
)
from characteros.storage.local_characters import LocalCharacterService
from characteros.services.queue_task_utils import effective_task_status
from characteros.storage.local_queue import LocalQueueManager

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


def _raw_task_dict(task: Any) -> dict | None:
    if task is None:
        return None
    if isinstance(task, dict):
        return task
    to_dict = getattr(task, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return dict(task)


def _normalized_task_payload(raw: Any, storage_mode: str) -> dict:
    """process / accept / reject 回傳與 list 端點一致的正規化 task 結構。"""
    payload = _raw_task_dict(raw)
    if not payload:
        raise ValueError("queue task payload is empty")
    return _task_item_from_dict(payload, storage_mode).model_dump(mode="json")


def _task_item_from_dict(raw: dict, storage_mode: str) -> QueueTaskItem:
    created = raw.get("created_at")
    updated = raw.get("updated_at")
    if isinstance(created, str):
        created = datetime.fromisoformat(created.replace("Z", "+00:00"))
    elif not isinstance(created, datetime):
        created = datetime.now(timezone.utc)
    if isinstance(updated, str):
        updated = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    elif not isinstance(updated, datetime):
        updated = created
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    result_metadata = copy.deepcopy(
        raw.get("result_metadata") if isinstance(raw.get("result_metadata"), dict) else {}
    )
    image_generation = (
        result_metadata.get("image_generation")
        if isinstance(result_metadata.get("image_generation"), dict)
        else {}
    )
    angles = result_metadata.get("angles") if isinstance(result_metadata.get("angles"), list) else image_generation.get("angles")
    if not isinstance(angles, list):
        angles = []

    computed_review_status = (
        str(raw.get("review_status") or "").strip()
        or str(result_metadata.get("review_status") or "").strip()
        or str(image_generation.get("review_status") or "").strip()
        or str((image_generation.get("review") or {}).get("status") or "").strip()
    )
    task_status = str(raw.get("status") or "").strip().lower()
    effective_status = effective_task_status(task_status, result_metadata)
    if effective_status == "accepted":
        computed_review_status = "accepted"
    elif not computed_review_status:
        computed_review_status = effective_status

    if computed_review_status == "rejected":
        strip_final_asset_path_from_image_generation(image_generation)
    elif computed_review_status == "pending":
        strip_final_asset_path_from_image_generation(image_generation)

    return QueueTaskItem(
        id=int(raw["id"]),
        core_id=int(raw["core_id"]),
        character_name=raw.get("character_name"),
        variant_hash=str(raw.get("variant_hash") or ""),
        evolution_params=raw.get("evolution_params") or {},
        status=str(raw.get("status") or "pending"),
        priority=int(raw.get("priority") or 0),
        error_message=raw.get("error_message"),
        retry_count=int(raw.get("retry_count") or 0),
        max_retries=int(raw.get("max_retries") or 3),
        result_url=raw.get("result_url"),
        result_metadata=result_metadata,
        review_status=computed_review_status or None,
        effective_status=effective_status,
        purpose=(
            str(raw.get("purpose") or "").strip()
            or str(result_metadata.get("purpose") or "").strip()
            or str(image_generation.get("purpose") or "").strip()
            or None
        ),
        angles=[str(item).strip() for item in angles if str(item).strip()],
        image_count=int(raw.get("image_count") or result_metadata.get("image_count") or 0),
        thumbnail_asset_path=(
            str(raw.get("thumbnail_asset_path") or "").strip()
            or str(result_metadata.get("thumbnail_asset_path") or "").strip()
            or str(image_generation.get("thumbnail_asset_path") or "").strip()
            or None
        ),
        face_detail_asset_path=(
            str(raw.get("face_detail_asset_path") or "").strip()
            or str(result_metadata.get("face_detail_asset_path") or "").strip()
            or str(image_generation.get("face_detail_asset_path") or "").strip()
            or None
        ),
        representative_asset_path=(
            str(raw.get("representative_asset_path") or "").strip()
            or str(result_metadata.get("representative_asset_path") or "").strip()
            or str(image_generation.get("representative_asset_path") or "").strip()
            or None
        ),
        representative_angle=(
            str(raw.get("representative_angle") or "").strip()
            or str(result_metadata.get("representative_angle") or "").strip()
            or str(image_generation.get("representative_angle") or "").strip()
            or None
        ),
        has_face_detail=bool(
            raw.get("has_face_detail")
            or result_metadata.get("has_face_detail")
            or image_generation.get("has_face_detail")
        ),
        face_detail_count=int(
            raw.get("face_detail_count")
            or result_metadata.get("face_detail_count")
            or image_generation.get("face_detail_count")
            or 0
        ),
        created_at=created,
        updated_at=updated,
    )


def _local_queue_payload(
    *,
    status: str | None,
    core_id: int | None,
    limit: int,
) -> QueueTaskListResponse:
    mgr = LocalQueueManager()
    stats = QueueStatsResponse(**mgr.get_queue_stats())
    raw_tasks = mgr.list_tasks(status=status, core_id=core_id, limit=limit)
    tasks = [_task_item_from_dict(t, "local") for t in raw_tasks]
    return QueueTaskListResponse(
        storage_mode="local",
        stats=stats,
        tasks=tasks,
        total=len(tasks),
    )


@router.get("/queue-stats", response_model=QueueStatsResponse)
def get_queue_stats(db: Session = Depends(get_db)):
    """取得佇列統計；DB 不可用時改讀本機 JSON 佇列。"""
    if not is_database_available():
        return QueueStatsResponse(**LocalQueueManager().get_queue_stats())
    try:
        queue_mgr = QueueManager(db)
        return QueueStatsResponse(**queue_mgr.get_queue_stats())
    except SQLAlchemyError:
        mark_database_unavailable()
        return QueueStatsResponse(**LocalQueueManager().get_queue_stats())


@router.get("/queue-tasks", response_model=QueueTaskListResponse)
def list_queue_tasks(
    status: Optional[str] = Query(None, description="pending / ready / failed"),
    core_id: Optional[int] = Query(None, description="依角色 ID 過濾"),
    limit: int = Query(200, ge=1, le=400, description="最多回傳筆數"),
    db: Session = Depends(get_db),
):
    """列出佇列任務明細，供 GUI 面板顯示。"""
    if not is_database_available():
        return _local_queue_payload(status=status, core_id=core_id, limit=limit)

    try:
        queue_mgr = QueueManager(db)
        stats = QueueStatsResponse(**queue_mgr.get_queue_stats())
        raw_tasks = queue_mgr.list_tasks(status=status, core_id=core_id, limit=limit)
        tasks = [_task_item_from_dict(t, "database") for t in raw_tasks]
        return QueueTaskListResponse(
            storage_mode="database",
            stats=stats,
            tasks=tasks,
            total=len(tasks),
        )
    except SQLAlchemyError:
        mark_database_unavailable()
        return _local_queue_payload(status=status, core_id=core_id, limit=limit)


def _local_age_span_status(
    *,
    core_id: int | None,
    pipeline_id: str | None,
) -> AgeSpanPipelineStatusResponse | None:
    summary = summarize_age_span_pipeline(
        LocalQueueManager().list_tasks(limit=400),
        core_id=core_id,
        pipeline_id=pipeline_id,
    )
    if not summary:
        return None
    return AgeSpanPipelineStatusResponse(**summary)


@router.get("/queue-tasks/age-span-status", response_model=AgeSpanPipelineStatusResponse)
def get_age_span_pipeline_status(
    core_id: Optional[int] = Query(None, description="依角色 ID 過濾"),
    pipeline_id: Optional[str] = Query(None, description="依 pipeline_id 過濾"),
    db: Session = Depends(get_db),
):
    """取得年齡軸 pipeline 進度與阻擋原因（需逐步接受後才能繼續）。"""
    if not is_database_available():
        summary = _local_age_span_status(core_id=core_id, pipeline_id=pipeline_id)
        if summary is None:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No age-span pipeline tasks found",
            )
        return summary

    try:
        from characteros.models.orm import CharacterVariant

        variants = db.query(CharacterVariant).all()
        task_dicts = [
            {
                "id": variant.id,
                "core_id": variant.core_id,
                "character_name": None,
                "status": variant.status,
                "priority": variant.priority,
                "evolution_params": variant.evolution_params or {},
                "result_metadata": variant.result_metadata or {},
                "created_at": variant.created_at.isoformat() if variant.created_at else "",
            }
            for variant in variants
        ]
        summary = summarize_age_span_pipeline(task_dicts, core_id=core_id, pipeline_id=pipeline_id)
        if summary is None:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No age-span pipeline tasks found",
            )
        return AgeSpanPipelineStatusResponse(**summary)
    except SQLAlchemyError:
        mark_database_unavailable()
        summary = _local_age_span_status(core_id=core_id, pipeline_id=pipeline_id)
        if summary is None:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No age-span pipeline tasks found",
            )
        return summary


@router.post("/queue-tasks/{task_id}/reset")
def reset_queue_task(task_id: int, db: Session = Depends(get_db)):
    """將 failed 任務重設為 pending，以便逐筆重試。"""
    if not is_database_available():
        task = LocalQueueManager().reset_task_to_pending(task_id)
        return {
            "storage_mode": "local",
            "reset": 1,
            "task": _normalized_task_payload(task, "local"),
        }

    try:
        task = QueueManager(db).reset_variant_to_pending(task_id)
        return {
            "storage_mode": "database",
            "reset": 1,
            "task": _normalized_task_payload(task, "database"),
        }
    except SQLAlchemyError:
        mark_database_unavailable()
        task = LocalQueueManager().reset_task_to_pending(task_id)
        return {
            "storage_mode": "local",
            "reset": 1,
            "task": _normalized_task_payload(task, "local"),
        }


@router.post("/queue-tasks/clear")
def clear_queue_tasks(
    core_id: Optional[int] = Query(None, description="僅清除指定角色的任務；省略則清空全部"),
    db: Session = Depends(get_db),
):
    """清空佇列任務列表。"""
    if not is_database_available():
        removed = LocalQueueManager().clear_tasks(core_id=core_id)
        return {
            "storage_mode": "local",
            "cleared": removed,
            "stats": QueueStatsResponse(**LocalQueueManager().get_queue_stats()),
        }

    try:
        removed = QueueManager(db).clear_tasks(core_id=core_id)
        return {
            "storage_mode": "database",
            "cleared": removed,
            "stats": QueueStatsResponse(**QueueManager(db).get_queue_stats()),
        }
    except SQLAlchemyError:
        mark_database_unavailable()
        removed = LocalQueueManager().clear_tasks(core_id=core_id)
        return {
            "storage_mode": "local",
            "cleared": removed,
            "stats": QueueStatsResponse(**LocalQueueManager().get_queue_stats()),
        }


@router.post("/queue-tasks/reset-failed")
def reset_failed_queue_tasks(
    core_id: Optional[int] = Query(None, description="僅重設指定角色的 failed 任務"),
    from_id: Optional[int] = Query(None, ge=1, description="僅重設 id >= from_id 的 failed 任務"),
    db: Session = Depends(get_db),
):
    """批次將 failed 任務重設為 waiting/pending。"""
    if not is_database_available():
        tasks = LocalQueueManager().reset_failed_tasks(core_id=core_id, from_id=from_id)
        resume_and_wake_queue_worker()
        return {
            "storage_mode": "local",
            "reset": len(tasks),
            "tasks": [_normalized_task_payload(task, "local") for task in tasks],
        }

    try:
        tasks = QueueManager(db).reset_failed_tasks(core_id=core_id, from_id=from_id)
        resume_and_wake_queue_worker()
        return {
            "storage_mode": "database",
            "reset": len(tasks),
            "tasks": [_normalized_task_payload(task, "database") for task in tasks],
        }
    except SQLAlchemyError:
        mark_database_unavailable()
        tasks = LocalQueueManager().reset_failed_tasks(core_id=core_id, from_id=from_id)
        resume_and_wake_queue_worker()
        return {
            "storage_mode": "local",
            "reset": len(tasks),
            "tasks": [_normalized_task_payload(task, "local") for task in tasks],
        }


@router.post("/queue-tasks/{task_id}/process")
def process_queue_task(task_id: int, db: Session = Depends(get_db)):
    """手動處理單一佇列任務，讓面板任務不只停留在 pending。"""
    if not is_database_available():
        service = LocalCharacterService()
        task = LocalQueueManager().process_task(task_id, character_service=service)
        return {
            "storage_mode": "local",
            "processed": 1,
            "task": _normalized_task_payload(task, "local"),
        }

    try:
        task = QueueManager(db).process_variant(task_id)
        return {
            "storage_mode": "database",
            "processed": 1,
            "task": _normalized_task_payload(task, "database"),
        }
    except SQLAlchemyError:
        mark_database_unavailable()
        service = LocalCharacterService()
        task = LocalQueueManager().process_task(task_id, character_service=service)
        return {
            "storage_mode": "local",
            "processed": 1,
            "task": _normalized_task_payload(task, "local"),
        }


@router.post("/queue-tasks/{task_id}/accept")
def accept_queue_task(task_id: int, db: Session = Depends(get_db)):
    """接受已完成的 AI 生圖任務，才正式寫回角色資料。"""
    if not is_database_available():
        service = LocalCharacterService()
        task = LocalQueueManager().review_task(task_id, accepted=True, character_service=service)
        return {
            "storage_mode": "local",
            "reviewed": 1,
            "task": _normalized_task_payload(task, "local"),
        }

    try:
        task = QueueManager(db).review_variant(task_id, accepted=True)
        return {
            "storage_mode": "database",
            "reviewed": 1,
            "task": _normalized_task_payload(task, "database"),
        }
    except SQLAlchemyError:
        mark_database_unavailable()
        service = LocalCharacterService()
        task = LocalQueueManager().review_task(task_id, accepted=True, character_service=service)
        return {
            "storage_mode": "local",
            "reviewed": 1,
            "task": _normalized_task_payload(task, "local"),
        }


@router.post("/queue-tasks/{task_id}/reject")
def reject_queue_task(task_id: int, db: Session = Depends(get_db)):
    """拒絕已完成的 AI 生圖任務，不寫回角色資料。"""
    if not is_database_available():
        service = LocalCharacterService()
        task = LocalQueueManager().review_task(task_id, accepted=False, character_service=service)
        return {
            "storage_mode": "local",
            "reviewed": 1,
            "task": _normalized_task_payload(task, "local"),
        }

    try:
        task = QueueManager(db).review_variant(task_id, accepted=False)
        return {
            "storage_mode": "database",
            "reviewed": 1,
            "task": _normalized_task_payload(task, "database"),
        }
    except SQLAlchemyError:
        mark_database_unavailable()
        service = LocalCharacterService()
        task = LocalQueueManager().review_task(task_id, accepted=False, character_service=service)
        return {
            "storage_mode": "local",
            "reviewed": 1,
            "task": _normalized_task_payload(task, "local"),
        }


@router.get("/queue-worker", response_model=QueueWorkerStatusResponse)
def get_queue_worker_status():
    """取得後端逐步生圖 worker 狀態。"""
    return QueueWorkerStatusResponse(**worker_status())


@router.post("/queue-worker/start", response_model=QueueWorkerStatusResponse)
def start_queue_worker_endpoint():
    """恢復並喚醒後端 worker，自動一次處理下一步。"""
    resume_and_wake_queue_worker()
    return QueueWorkerStatusResponse(**worker_status())


@router.post("/queue-worker/pause", response_model=QueueWorkerStatusResponse)
def pause_queue_worker_endpoint():
    """暫停後端 worker；目前進行中的那一筆仍會跑完。"""
    set_worker_paused(True)
    return QueueWorkerStatusResponse(**worker_status())


@router.post("/queue-tasks/process-next")
def process_next_queue_task(
    core_id: Optional[int] = Query(None, description="僅處理指定角色的下一筆任務"),
    db: Session = Depends(get_db),
):
    """處理下一筆 pending 任務。"""
    if not is_database_available():
        service = LocalCharacterService()
        mgr = LocalQueueManager()
        task = mgr.process_next(character_service=service, core_id=core_id)
        summary = summarize_age_span_pipeline(mgr.list_tasks(limit=400), core_id=core_id)
        return {
            "storage_mode": "local",
            "processed": 0 if task is None else 1,
            "blocked": False,
            "age_span": summary,
            "task": None if task is None else _normalized_task_payload(task, "local"),
        }

    try:
        queue_mgr = QueueManager(db)
        task = queue_mgr.process_next_pending(core_id=core_id)
        from characteros.models.orm import CharacterVariant

        variants = db.query(CharacterVariant).all()
        task_dicts = [
            {
                "id": variant.id,
                "core_id": variant.core_id,
                "status": variant.status,
                "priority": variant.priority,
                "evolution_params": variant.evolution_params or {},
                "result_metadata": variant.result_metadata or {},
                "created_at": variant.created_at.isoformat() if variant.created_at else "",
            }
            for variant in variants
        ]
        if core_id is not None:
            task_dicts = [task for task in task_dicts if int(task.get("core_id", 0)) == int(core_id)]
        summary = summarize_age_span_pipeline(task_dicts, core_id=core_id)
        return {
            "storage_mode": "database",
            "processed": 0 if task is None else 1,
            "blocked": False,
            "age_span": summary,
            "task": None if task is None else _normalized_task_payload(task, "database"),
        }
    except SQLAlchemyError:
        mark_database_unavailable()
        service = LocalCharacterService()
        mgr = LocalQueueManager()
        task = mgr.process_next(character_service=service, core_id=core_id)
        summary = summarize_age_span_pipeline(mgr.list_tasks(limit=400), core_id=core_id)
        return {
            "storage_mode": "local",
            "processed": 0 if task is None else 1,
            "blocked": False,
            "age_span": summary,
            "task": None if task is None else _normalized_task_payload(task, "local"),
        }


@router.post("/queue-tasks/process-all")
def process_all_queue_tasks(
    limit: int = Query(1, ge=1, le=200, description="本次最多處理幾筆 pending 任務（年齡軸固定為 1）"),
    core_id: Optional[int] = Query(None, description="僅處理指定角色"),
    db: Session = Depends(get_db),
):
    """批次處理 pending 任務。年齡軸 pipeline 存在時強制一次只處理 1 筆。"""
    effective_limit = limit
    if not is_database_available():
        tasks = LocalQueueManager().list_tasks(limit=400)
        if core_id is not None:
            tasks = [task for task in tasks if int(task.get("core_id", 0)) == int(core_id)]
        if summarize_age_span_pipeline(tasks, core_id=core_id):
            effective_limit = 1
        service = LocalCharacterService()
        processed_tasks = LocalQueueManager().process_all(
            limit=effective_limit,
            character_service=service,
        )
        return {
            "storage_mode": "local",
            "processed": len(processed_tasks),
            "limit_applied": effective_limit,
            "tasks": [_normalized_task_payload(task, "local") for task in processed_tasks],
        }

    try:
        from characteros.models.orm import CharacterVariant

        variants = db.query(CharacterVariant).all()
        task_dicts = [
            {
                "id": variant.id,
                "core_id": variant.core_id,
                "status": variant.status,
                "priority": variant.priority,
                "evolution_params": variant.evolution_params or {},
                "result_metadata": variant.result_metadata or {},
                "created_at": variant.created_at.isoformat() if variant.created_at else "",
            }
            for variant in variants
        ]
        if core_id is not None:
            task_dicts = [task for task in task_dicts if int(task.get("core_id", 0)) == int(core_id)]
        if summarize_age_span_pipeline(task_dicts, core_id=core_id):
            effective_limit = 1
        tasks = QueueManager(db).process_all_pending(limit=effective_limit)
        return {
            "storage_mode": "database",
            "processed": len(tasks),
            "limit_applied": effective_limit,
            "tasks": [_normalized_task_payload(task, "database") for task in tasks],
        }
    except SQLAlchemyError:
        mark_database_unavailable()
        tasks = LocalQueueManager().list_tasks(limit=400)
        if core_id is not None:
            tasks = [task for task in tasks if int(task.get("core_id", 0)) == int(core_id)]
        if summarize_age_span_pipeline(tasks, core_id=core_id):
            effective_limit = 1
        service = LocalCharacterService()
        processed_tasks = LocalQueueManager().process_all(
            limit=effective_limit,
            character_service=service,
        )
        return {
            "storage_mode": "local",
            "processed": len(processed_tasks),
            "limit_applied": effective_limit,
            "tasks": [_normalized_task_payload(task, "local") for task in processed_tasks],
        }


@router.get("/metrics", response_model=SystemMetricsResponse)
def get_system_metrics(db: Session = Depends(get_db)):
    """取得系統效能指標（管理用）。"""
    if not is_database_available():
        local = LocalCharacterService()
        result = local.list_characters(skip=0, limit=1000)
        total = int(result.get("total", 0)) if isinstance(result, dict) else len(result)
        qstats = LocalQueueManager().get_queue_stats()
        return SystemMetricsResponse(
            database_connections=0,
            cache_hit_rate=0.0,
            api_response_time_p95_ms=0.0,
            total_characters=total,
            total_profiles=total,
            total_variants=(
                qstats["total_pending"] + qstats.get("total_waiting", 0) + qstats["total_ready"] + qstats["total_failed"]
            ),
        )

    from characteros.models.orm import CharacterCore, CharacterProfile, CharacterVariant
    from sqlalchemy import func

    try:
        total_characters = db.query(func.count(CharacterCore.id)).scalar() or 0
        total_profiles = db.query(func.count(CharacterProfile.id)).scalar() or 0
        total_variants = db.query(func.count(CharacterVariant.id)).scalar() or 0
    except SQLAlchemyError:
        mark_database_unavailable()
        local = LocalCharacterService()
        result = local.list_characters(skip=0, limit=1000)
        total = int(result.get("total", 0)) if isinstance(result, dict) else len(result)
        qstats = LocalQueueManager().get_queue_stats()
        return SystemMetricsResponse(
            database_connections=0,
            cache_hit_rate=0.0,
            api_response_time_p95_ms=0.0,
            total_characters=total,
            total_profiles=total,
            total_variants=(
                qstats["total_pending"] + qstats.get("total_waiting", 0) + qstats["total_ready"] + qstats["total_failed"]
            ),
        )

    return SystemMetricsResponse(
        database_connections=1,
        cache_hit_rate=0.0,
        api_response_time_p95_ms=0.0,
        total_characters=total_characters,
        total_profiles=total_profiles,
        total_variants=total_variants,
    )


@router.get("/imaging-config", response_model=ImagingConfigResponse)
def get_imaging_config(db: Session = Depends(get_db)):
    """讀取目前生圖設定（API key 僅回傳是否存在；來源：DB / .env）。"""
    if is_database_available():
        try:
            settings.load_from_db(db)
        except Exception:
            mark_database_unavailable()

    snap = settings.snapshot()
    return ImagingConfigResponse(
        provider=snap.provider,
        base_url=snap.base_url,
        model=snap.model,
        has_api_key=snap.has_api_key,
    )


@router.put("/imaging-config", response_model=ImagingConfigResponse)
def update_imaging_config(body: ImagingConfigUpdateRequest, db: Session = Depends(get_db)):
    """更新生圖設定：寫入 DB 並同步 .env（provider / endpoint / model / api_key）。"""
    use_db = is_database_available()
    if use_db:
        try:
            snap = settings.update(
                db,
                provider=body.provider,
                base_url=body.base_url,
                model=body.model,
                api_key=body.api_key,
                clear_api_key=body.clear_api_key,
                persist_env=body.persist_env,
            )
            return ImagingConfigResponse(
                provider=snap.provider,
                base_url=snap.base_url,
                model=snap.model,
                has_api_key=snap.has_api_key,
            )
        except Exception:
            mark_database_unavailable()

    snap = settings.update_env_only(
        provider=body.provider,
        base_url=body.base_url,
        model=body.model,
        api_key=body.api_key,
        clear_api_key=body.clear_api_key,
        persist_env=body.persist_env,
    )

    return ImagingConfigResponse(
        provider=snap.provider,
        base_url=snap.base_url,
        model=snap.model,
        has_api_key=snap.has_api_key,
    )
