"""人物圖像生成管線。

模組分工：
- `image_pipeline` — 入列入口（按需 variant / 可選 fill_span）
- `pipeline_coordinator` — 同一次請求內 waiting/pending 協調、動態入列下一步
- `image_task_runner` — 單步生圖執行（local / DB 共用）
- `queue_worker` — 後端逐步 worker（一次一張，失敗暫停）

年齡軸是 `character_variants` 的特殊案例：`request_params = {age, emotion, scene, ...}`。
預設只生成請求的歲數；`fill_span=true` 才補齊區間。生成前查快取，命中則直接回傳。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from characteros.models.schema import ImageQueueRequest
from characteros.services.age_span import (
    AGE_SPAN_END,
    AGE_SPAN_START,
    age_span_steps,
    build_age_span_evolution_params,
    new_pipeline_id,
    should_queue_age_span,
    step_priority,
)
from characteros.storage.db_availability import is_database_available
from characteros.storage.local_characters import LocalCharacterService
from characteros.storage.local_queue import LocalQueueManager
from characteros.imaging.settings import settings as imaging_settings


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


def _task_status(task: dict[str, Any] | None) -> str:
    if not task:
        return ""
    return str(task.get("status") or "").strip().lower()


def _as_task_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "to_dict"):
        return dict(item.to_dict())
    return {}


def _request_variant(
    *,
    character_id: int,
    evolution_params: dict[str, Any],
    priority: int,
    char_name: str | None,
    local_mode: bool,
    db: Session | None,
    status: str = "pending",
) -> tuple[dict[str, Any], bool]:
    if local_mode:
        task, is_new = LocalQueueManager().request_variant_generation(
            core_id=character_id,
            evolution_params=evolution_params,
            priority=priority,
            character_name=char_name,
            status=status,
        )
        return task, is_new
    from characteros.services.queue import QueueManager

    variant, is_new = QueueManager(db).request_variant_generation(
        core_id=character_id,
        evolution_params=evolution_params,
        priority=priority,
        status=status,
    )
    return variant.to_dict(), is_new


def _target_age_for_body(body: ImageQueueRequest, *, base_age: int | None) -> int:
    if body.age is not None:
        return int(body.age)
    if body.age_start is not None and (body.age_end is None or int(body.age_end) == int(body.age_start)):
        return int(body.age_start)
    if base_age is not None:
        return max(AGE_SPAN_START, min(AGE_SPAN_END, int(base_age)))
    return 25


def _enqueue_age_span(
    *,
    character_id: int,
    body: ImageQueueRequest,
    char_name: str | None,
    local_mode: bool,
    db: Session | None,
    base_age: int | None = None,
) -> dict[str, Any]:
    fill_span = bool(body.fill_span)
    if fill_span:
        if body.age_start is None or body.age_end is None:
            raise ValueError("fill_span requires both age_start and age_end")
        start = int(body.age_start)
        end = int(body.age_end)
        steps = age_span_steps(age_start=start, age_end=end, fill_span=True)
    else:
        target = _target_age_for_body(body, base_age=base_age)
        steps = age_span_steps(age=target, fill_span=False)
        start = end = target

    pipeline_id = new_pipeline_id()
    queued: list[dict[str, Any]] = []
    created = 0
    cache_hits = 0
    first_pending: dict[str, Any] | None = None

    for step in steps:
        evolution_params = build_age_span_evolution_params(
            step,
            pipeline_id=pipeline_id,
            provider=_resolved_queue_provider(body),
            model=_resolved_queue_model(body),
            base_url=_resolved_queue_base_url(body),
            api_key=body.api_key,
            extra=body.extra,
            persist=body.persist,
            entity_id=body.entity_id,
            emotion=body.emotion,
            scene=body.scene,
            weather=body.weather,
            injury=body.injury,
            lora=getattr(body, "lora", None),
        )
        priority = step_priority(body.priority, step)
        task, is_new = _request_variant(
            character_id=character_id,
            evolution_params=evolution_params,
            priority=priority,
            char_name=char_name,
            local_mode=local_mode,
            db=db,
            status="pending",
        )
        queued.append(task)
        if is_new:
            created += 1
        elif _task_status(task) == "ready":
            cache_hits += 1
        if _task_status(task) != "ready" and first_pending is None:
            first_pending = task
            break

    all_ready = bool(queued) and all(_task_status(item) == "ready" for item in queued) and created == 0
    return {
        "storage_mode": "local" if local_mode else "database",
        "queued": not all_ready,
        "cache_hit": all_ready or (created == 0 and cache_hits > 0 and first_pending is None),
        "pipeline": "age_span",
        "pipeline_id": pipeline_id,
        "is_new": created > 0,
        "created": created,
        "total": len(steps),
        "age": start if start == end else None,
        "age_start": start,
        "age_end": end,
        "fill_span": fill_span,
        "auto_start": True,
        "tasks": queued,
        "task": first_pending or (queued[0] if queued else None),
    }


def _build_single_evolution_params(body: ImageQueueRequest) -> dict[str, Any]:
    evolution_params: dict[str, Any] = {}
    if body.age is not None:
        evolution_params["age_override"] = body.age
    if body.emotion is not None:
        evolution_params["emotion_state"] = body.emotion
    if body.scene is not None:
        evolution_params["scene_context"] = body.scene
    if body.weather is not None:
        evolution_params["weather"] = body.weather
    if body.injury is not None:
        evolution_params["injury_level"] = body.injury
    if str(body.purpose or "").strip():
        evolution_params["purpose"] = str(body.purpose).strip()

    extra = str(body.extra or "").strip()
    if extra:
        evolution_params["user_extra"] = extra

    image_request: dict[str, Any] = {
        "purpose": body.purpose,
        "provider": _resolved_queue_provider(body),
        "model": _resolved_queue_model(body),
        "base_url": _resolved_queue_base_url(body),
        "extra": extra,
        "user_extra": extra,
        "n": body.n,
        "multi_angle": body.multi_angle,
        "persist": body.persist,
        "entity_id": body.entity_id,
    }
    lora = str(getattr(body, "lora", None) or "").strip()
    if lora:
        image_request["lora"] = lora
    if body.age is not None:
        token = f"{int(body.age):03d}"
        image_request["age"] = int(body.age)
        image_request["pipeline"] = "variant"
        image_request["asset_dir"] = f"assets/{body.purpose}/age_{token}"
        image_request["filename_prefix"] = f"ref_{body.purpose}_age_{token}"
    evolution_params["_image_request"] = image_request
    return evolution_params


def _enqueue_single(
    *,
    character_id: int,
    body: ImageQueueRequest,
    char_name: str | None,
    local_mode: bool,
    db: Session | None,
) -> dict[str, Any]:
    evolution_params = _build_single_evolution_params(body)
    task, is_new = _request_variant(
        character_id=character_id,
        evolution_params=evolution_params,
        priority=body.priority,
        char_name=char_name,
        local_mode=local_mode,
        db=db,
    )
    ready = _task_status(task) == "ready"
    return {
        "storage_mode": "local" if local_mode else "database",
        "queued": not ready,
        "cache_hit": ready and not is_new,
        "pipeline": None,
        "is_new": is_new,
        "created": 1 if is_new else 0,
        "total": 1,
        "auto_start": True,
        "task": task,
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
    base_age = int(full.core.base_age) if full and full.core and full.core.base_age is not None else None
    local_mode = isinstance(service, LocalCharacterService) or not is_database_available()

    if should_queue_age_span(body.purpose, manifest):
        result = _enqueue_age_span(
            character_id=character_id,
            body=body,
            char_name=char_name,
            local_mode=local_mode,
            db=db,
            base_age=base_age,
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

    if result.get("queued"):
        resume_and_wake_queue_worker()
    return result
