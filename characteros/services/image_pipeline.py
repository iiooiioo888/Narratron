"""人物圖像生成管線。

模組分工：
- `image_pipeline` — 入列入口（新人物 age_span / 單次用途）
- `pipeline_coordinator` — 年齡軸 waiting/pending 協調、動態入列下一步
- `image_task_runner` — 單步生圖執行（local / DB 共用）
- `queue_worker` — 後端逐步 worker（一次一張，失敗暫停）

新人物（無參考圖）或明確選擇 age_span：
  只入列「下一步」→ worker 一次生一張 → 自動入庫 → 再入列下一步。
  順序固定：face_detail 1–80，再 tpose 1–80。

已有參考圖的單次用途（identity / face_detail / tpose / outfit …）：
  入列一筆獨立任務，同樣由 worker 自動處理。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from characteros.models.schema import ImageQueueRequest
from characteros.services.age_span import (
    age_span_steps,
    build_age_span_evolution_params,
    find_open_age_span_pipeline_id,
    new_pipeline_id,
    should_queue_age_span,
    step_priority,
    tasks_for_pipeline,
)
from characteros.storage.db_availability import is_database_available
from characteros.storage.local_characters import LocalCharacterService
from characteros.storage.local_queue import LocalQueueManager
from characteros.imaging.settings import settings as imaging_settings


TASK_LIST_LIMIT = 400


def _resolved_queue_provider(body: ImageQueueRequest) -> str | None:
    """入列時寫入實際 provider；未指定則用全域生圖設定，避免默默變成 null 占位圖。"""
    raw = body.provider
    if raw is not None and str(raw).strip():
        return str(raw).strip().lower()
    configured = str(imaging_settings.get_provider() or "").strip().lower()
    return configured or None


def _resolved_queue_model(body: ImageQueueRequest) -> str | None:
    if body.model is not None and str(body.model).strip():
        return str(body.model).strip()
    configured = str(imaging_settings.get_model() or "").strip()
    return configured or None


def _resolved_queue_base_url(body: ImageQueueRequest) -> str | None:
    if body.base_url is not None and str(body.base_url).strip():
        return str(body.base_url).strip()
    configured = str(imaging_settings.get_base_url() or "").strip()
    return configured or None


def _list_tasks(character_id: int, *, local_mode: bool, db: Session | None) -> list[dict[str, Any]]:
    if local_mode:
        return LocalQueueManager().list_tasks(core_id=character_id, limit=TASK_LIST_LIMIT)
    from characteros.services.queue import QueueManager

    return QueueManager(db).list_tasks(core_id=character_id, limit=TASK_LIST_LIMIT)


def _ensure_following_steps(*, character_id: int, local_mode: bool, db: Session | None) -> None:
    if local_mode:
        LocalQueueManager().ensure_following_age_span_tasks(core_id=character_id)
        return
    from characteros.services.queue import QueueManager

    QueueManager(db).ensure_following_age_span_tasks(core_id=character_id)


def _enqueue_age_span(
    *,
    character_id: int,
    body: ImageQueueRequest,
    char_name: str | None,
    local_mode: bool,
    db: Session | None,
) -> dict[str, Any]:
    existing_tasks = _list_tasks(character_id, local_mode=local_mode, db=db)
    open_pipeline_id = find_open_age_span_pipeline_id(existing_tasks)
    if open_pipeline_id:
        _ensure_following_steps(character_id=character_id, local_mode=local_mode, db=db)
        existing_pipeline_tasks = tasks_for_pipeline(
            _list_tasks(character_id, local_mode=local_mode, db=db),
            open_pipeline_id,
        )
        first_request = {}
        if existing_pipeline_tasks:
            params = existing_pipeline_tasks[0].get("evolution_params") or {}
            image_request = params.get("_image_request") if isinstance(params, dict) else {}
            first_request = dict(image_request) if isinstance(image_request, dict) else {}
        total = int(first_request.get("total_steps") or len(existing_pipeline_tasks))
        return {
            "storage_mode": "local" if local_mode else "database",
            "queued": True,
            "pipeline": "age_span",
            "pipeline_id": open_pipeline_id,
            "is_new": False,
            "created": 0,
            "total": total,
            "age_start": body.age_start,
            "age_end": body.age_end,
            "auto_start": True,
            "tasks": existing_pipeline_tasks,
        }

    pipeline_id = new_pipeline_id()
    steps = age_span_steps(age_start=body.age_start, age_end=body.age_end)
    first_step = steps[0]
    evolution_params = build_age_span_evolution_params(
        first_step,
        pipeline_id=pipeline_id,
        provider=_resolved_queue_provider(body),
        model=_resolved_queue_model(body),
        base_url=_resolved_queue_base_url(body),
        api_key=body.api_key,
        extra=body.extra,
        persist=body.persist,
        entity_id=body.entity_id,
    )
    priority = step_priority(body.priority, first_step)
    if local_mode:
        task, is_new = LocalQueueManager().request_variant_generation(
            core_id=character_id,
            evolution_params=evolution_params,
            priority=priority,
            character_name=char_name,
            status="pending",
        )
        queued = [task]
    else:
        from characteros.services.queue import QueueManager

        variant, is_new = QueueManager(db).request_variant_generation(
            core_id=character_id,
            evolution_params=evolution_params,
            priority=priority,
            status="pending",
        )
        queued = [variant.to_dict()]

    return {
        "storage_mode": "local" if local_mode else "database",
        "queued": True,
        "pipeline": "age_span",
        "pipeline_id": pipeline_id,
        "is_new": is_new,
        "created": 1 if is_new else 0,
        "total": len(steps),
        "age_start": body.age_start,
        "age_end": body.age_end,
        "auto_start": True,
        "tasks": queued,
    }


def _enqueue_single(
    *,
    character_id: int,
    body: ImageQueueRequest,
    char_name: str | None,
    local_mode: bool,
    db: Session | None,
) -> dict[str, Any]:
    evolution_params: dict[str, Any] = {}
    if body.age is not None:
        evolution_params["age_override"] = body.age
    if body.emotion is not None:
        evolution_params["emotion_state"] = body.emotion
    if body.scene is not None:
        evolution_params["scene_context"] = body.scene
    if body.injury is not None:
        evolution_params["injury_level"] = body.injury

    evolution_params["_queue_nonce"] = f"img-{uuid4()}"
    evolution_params["_image_request"] = {
        "purpose": body.purpose,
        "provider": _resolved_queue_provider(body),
        "model": _resolved_queue_model(body),
        "base_url": _resolved_queue_base_url(body),
        "extra": body.extra,
        "n": body.n,
        "multi_angle": body.multi_angle,
        "persist": body.persist,
        "entity_id": body.entity_id,
    }

    if local_mode:
        task, is_new = LocalQueueManager().request_variant_generation(
            core_id=character_id,
            evolution_params=evolution_params,
            priority=body.priority,
            character_name=char_name,
        )
        return {
            "storage_mode": "local",
            "queued": True,
            "pipeline": None,
            "is_new": is_new,
            "created": 1 if is_new else 0,
            "total": 1,
            "auto_start": True,
            "task": task,
        }

    from characteros.services.queue import QueueManager

    variant, is_new = QueueManager(db).request_variant_generation(
        core_id=character_id,
        evolution_params=evolution_params,
        priority=body.priority,
    )
    return {
        "storage_mode": "database",
        "queued": True,
        "pipeline": None,
        "is_new": is_new,
        "created": 1 if is_new else 0,
        "total": 1,
        "auto_start": True,
        "task": variant.to_dict(),
    }


def enqueue_character_images(
    *,
    character_id: int,
    body: ImageQueueRequest,
    service: Any,
    db: Session | None,
) -> dict[str, Any]:
    """排入生圖任務，並喚醒後端逐步 worker（一次只處理下一步）。"""
    full = service.get_character_by_id(character_id)
    manifest: dict[str, Any] = {}
    if full.profile and full.profile.manifest:
        manifest = dict(full.profile.manifest)
    char_name = full.core.name if full and full.core else None
    local_mode = isinstance(service, LocalCharacterService) or not is_database_available()

    if should_queue_age_span(body.purpose, manifest):
        result = _enqueue_age_span(
            character_id=character_id,
            body=body,
            char_name=char_name,
            local_mode=local_mode,
            db=db,
        )
    else:
        result = _enqueue_single(
            character_id=character_id,
            body=body,
            char_name=char_name,
            local_mode=local_mode,
            db=db,
        )

    from characteros.services.queue_worker import resume_and_wake_queue_worker

    resume_and_wake_queue_worker()
    return result
