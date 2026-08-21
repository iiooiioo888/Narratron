"""年齡軸 pipeline 協調：同步 waiting/pending、動態入列下一步。

人物圖像生成主流程（local / DB 共用）：

1. **入列**（image_pipeline.enqueue_character_images）
   - 按需：只入列請求歲數的下一步（通常是 face_detail）。
   - fill_span：才會依區間逐步銜接。
2. **後端 worker**（queue_worker）
   - 一次只 process 一筆 pending；失敗即暫停。
3. **單步生圖**（local_queue / queue.process_*）
   - 優先復用 character_variants 快取；未命中才呼叫 ImagingService。
4. **銜接下一步**（本模組 enqueue_next_age_span_steps）
   - 僅限本次請求規劃的步驟（同歲 T 型，或 fill_span 的下一歲）。
5. **正規化**（normalize_age_span_queue）
   - 每個 pipeline 同時最多一筆 pending。
"""

from __future__ import annotations

from typing import Any, Callable

from characteros.services.age_span import (
    activate_next_waiting_task,
    initial_queue_status,
    next_enqueue_payload,
    normalize_age_span_queue,
    pipeline_groups,
)

EnqueueFn = Callable[..., tuple[Any, bool]]


def sync_age_span_task_states(tasks: list[dict[str, Any]]) -> None:
    """收斂年齡軸 waiting/pending，並啟動下一筆可執行步驟。"""
    normalize_age_span_queue(tasks)
    activate_next_waiting_task(tasks)


def enqueue_next_age_span_steps(
    tasks: list[dict[str, Any]],
    *,
    enqueue: EnqueueFn,
    core_id: int | None = None,
) -> list[Any]:
    """已完成步驟後，為每個 open pipeline 動態入列下一步（若尚未存在）。"""
    created: list[Any] = []
    for pipeline_id in list(pipeline_groups(tasks).keys()):
        payload = next_enqueue_payload(tasks, pipeline_id)
        if not payload:
            continue
        if core_id is not None and int(payload.get("core_id") or 0) != int(core_id):
            continue
        step = payload.get("step") if isinstance(payload.get("step"), dict) else {}
        status = initial_queue_status(step) if step else "pending"
        task, is_new = enqueue(
            core_id=int(payload["core_id"]),
            evolution_params=payload["evolution_params"],
            priority=int(payload.get("priority") or 0),
            character_name=payload.get("character_name"),
            status=status,
        )
        if is_new:
            created.append(task)
    return created


def prepare_for_processing(
    tasks: list[dict[str, Any]],
    *,
    enqueue: EnqueueFn,
    core_id: int | None = None,
) -> None:
    """process_next 前：補齊下一步任務並正規化狀態。"""
    enqueue_next_age_span_steps(tasks, enqueue=enqueue, core_id=core_id)
    sync_age_span_task_states(tasks)


def after_image_task_succeeded(
    tasks: list[dict[str, Any]],
    *,
    enqueue: EnqueueFn,
    core_id: int | None = None,
    wake_worker: bool = True,
    reload_tasks: Callable[[], list[dict[str, Any]]] | None = None,
) -> list[Any]:
    """單步生圖成功後：動態入列下一步、正規化 waiting/pending，並喚醒 worker。"""
    created = enqueue_next_age_span_steps(tasks, enqueue=enqueue, core_id=core_id)
    if reload_tasks is not None:
        tasks[:] = reload_tasks()
    sync_age_span_task_states(tasks)
    if wake_worker:
        from characteros.services.queue_worker import wake_queue_worker

        wake_queue_worker()
    return created
