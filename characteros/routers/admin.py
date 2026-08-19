"""CharacterOS 管理路由：佇列統計與系統指標。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from characteros.imaging.settings import settings
from characteros.models.database import get_db
from characteros.models.schema import (
    ImagingConfigResponse,
    ImagingConfigUpdateRequest,
    QueueStatsResponse,
    QueueTaskItem,
    QueueTaskListResponse,
    SystemMetricsResponse,
)
from characteros.services.queue import QueueManager
from characteros.storage.db_availability import (
    is_database_available,
    mark_database_unavailable,
)
from characteros.storage.local_characters import LocalCharacterService
from characteros.storage.local_queue import LocalQueueManager

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


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
        result_metadata=raw.get("result_metadata") or {},
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
    limit: int = Query(50, ge=1, le=200, description="最多回傳筆數"),
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


@router.post("/queue-tasks/{task_id}/process")
def process_queue_task(task_id: int, db: Session = Depends(get_db)):
    """手動處理單一佇列任務，讓面板任務不只停留在 pending。"""
    if not is_database_available():
        service = LocalCharacterService()
        task = LocalQueueManager().process_task(task_id, character_service=service)
        return {
            "storage_mode": "local",
            "processed": 1,
            "task": task,
        }

    try:
        task = QueueManager(db).process_variant(task_id)
        return {
            "storage_mode": "database",
            "processed": 1,
            "task": task.to_dict(),
        }
    except SQLAlchemyError:
        mark_database_unavailable()
        service = LocalCharacterService()
        task = LocalQueueManager().process_task(task_id, character_service=service)
        return {
            "storage_mode": "local",
            "processed": 1,
            "task": task,
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
            "task": task,
        }

    try:
        task = QueueManager(db).review_variant(task_id, accepted=True)
        return {
            "storage_mode": "database",
            "reviewed": 1,
            "task": task.to_dict(),
        }
    except SQLAlchemyError:
        mark_database_unavailable()
        service = LocalCharacterService()
        task = LocalQueueManager().review_task(task_id, accepted=True, character_service=service)
        return {
            "storage_mode": "local",
            "reviewed": 1,
            "task": task,
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
            "task": task,
        }

    try:
        task = QueueManager(db).review_variant(task_id, accepted=False)
        return {
            "storage_mode": "database",
            "reviewed": 1,
            "task": task.to_dict(),
        }
    except SQLAlchemyError:
        mark_database_unavailable()
        service = LocalCharacterService()
        task = LocalQueueManager().review_task(task_id, accepted=False, character_service=service)
        return {
            "storage_mode": "local",
            "reviewed": 1,
            "task": task,
        }


@router.post("/queue-tasks/process-next")
def process_next_queue_task(db: Session = Depends(get_db)):
    """處理下一筆 pending 任務。"""
    if not is_database_available():
        service = LocalCharacterService()
        task = LocalQueueManager().process_next(character_service=service)
        return {
            "storage_mode": "local",
            "processed": 0 if task is None else 1,
            "task": task,
        }

    try:
        task = QueueManager(db).process_next_pending()
        return {
            "storage_mode": "database",
            "processed": 0 if task is None else 1,
            "task": None if task is None else task.to_dict(),
        }
    except SQLAlchemyError:
        mark_database_unavailable()
        service = LocalCharacterService()
        task = LocalQueueManager().process_next(character_service=service)
        return {
            "storage_mode": "local",
            "processed": 0 if task is None else 1,
            "task": task,
        }


@router.post("/queue-tasks/process-all")
def process_all_queue_tasks(
    limit: int = Query(20, ge=1, le=200, description="本次最多處理幾筆 pending 任務"),
    db: Session = Depends(get_db),
):
    """批次處理多筆 pending 任務。"""
    if not is_database_available():
        service = LocalCharacterService()
        tasks = LocalQueueManager().process_all(limit=limit, character_service=service)
        return {
            "storage_mode": "local",
            "processed": len(tasks),
            "tasks": tasks,
        }

    try:
        tasks = QueueManager(db).process_all_pending(limit=limit)
        return {
            "storage_mode": "database",
            "processed": len(tasks),
            "tasks": [task.to_dict() for task in tasks],
        }
    except SQLAlchemyError:
        mark_database_unavailable()
        service = LocalCharacterService()
        tasks = LocalQueueManager().process_all(limit=limit, character_service=service)
        return {
            "storage_mode": "local",
            "processed": len(tasks),
            "tasks": tasks,
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
                qstats["total_pending"] + qstats["total_ready"] + qstats["total_failed"]
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
                qstats["total_pending"] + qstats["total_ready"] + qstats["total_failed"]
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
