"""後端逐步生圖 worker：一次只處理一筆 pending，完成並入庫後再接下一步。"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

_wake = threading.Event()
_lock = threading.Lock()
_thread: threading.Thread | None = None
_busy = False
_last_task_id: int | None = None
_last_status: str | None = None
_last_error: str | None = None


def _local_paused() -> bool:
    from characteros.storage.local_queue import LocalQueueManager

    return bool(LocalQueueManager().get_worker_control().get("paused"))


def set_worker_paused(paused: bool) -> dict[str, Any]:
    from characteros.storage.db_availability import is_database_available
    from characteros.storage.local_queue import LocalQueueManager

    control = LocalQueueManager().set_worker_paused(paused)
    if is_database_available():
        # DB 模式仍共用本機 JSON 的暫停旗標，避免雙重執行。
        pass
    if not paused:
        wake_queue_worker()
    return control


def _current_running_snapshot() -> dict[str, Any] | None:
    try:
        from characteros.services.age_span import _task_image_request, step_phrase
        from characteros.storage.local_queue import LocalQueueManager

        running = [
            task
            for task in LocalQueueManager().list_tasks(limit=400)
            if str(task.get("status") or "").strip().lower() == "running"
        ]
        if not running:
            return None
        task = running[0]
        req = _task_image_request(task)
        age = req.get("age")
        try:
            age_int = int(age) if age is not None and age != "" else None
        except (TypeError, ValueError):
            age_int = None
        step_index = req.get("step_index")
        total_steps = req.get("total_steps")
        try:
            step_index = int(step_index) if step_index is not None else None
        except (TypeError, ValueError):
            step_index = None
        try:
            total_steps = int(total_steps) if total_steps is not None else None
        except (TypeError, ValueError):
            total_steps = None
        return {
            "id": int(task.get("id") or 0),
            "core_id": int(task.get("core_id") or 0) or None,
            "character_name": task.get("character_name"),
            "status": "running",
            "purpose": req.get("purpose") or req.get("phase"),
            "phase": req.get("phase"),
            "age": age_int,
            "step_index": step_index,
            "total_steps": total_steps,
            "started_at": task.get("started_at") or task.get("updated_at"),
            "label": step_phrase(req),
        }
    except Exception:
        return None


def worker_status() -> dict[str, Any]:
    paused = _local_paused()
    pending = 0
    waiting = 0
    running = 0
    failed = 0
    try:
        from characteros.storage.local_queue import LocalQueueManager

        stats = LocalQueueManager().get_queue_stats()
        pending = int(stats.get("total_pending") or 0)
        waiting = int(stats.get("total_waiting") or 0)
        running = int(stats.get("total_running") or 0)
        failed = int(stats.get("total_failed") or 0)
    except Exception:
        pass
    current = _current_running_snapshot()
    return {
        "paused": paused,
        "busy": _busy or running > 0,
        "auto_run": (not paused) and (_busy or pending > 0 or waiting > 0 or running > 0),
        "last_task_id": _last_task_id,
        "last_status": _last_status,
        "last_error": _last_error,
        "current_task": current,
        "pending_count": pending,
        "waiting_count": waiting,
        "running_count": running,
        "failed_count": failed,
    }


def wake_queue_worker() -> None:
    _wake.set()
    start_queue_worker()


def resume_and_wake_queue_worker() -> None:
    from characteros.storage.local_queue import LocalQueueManager

    LocalQueueManager().set_worker_paused(False)
    wake_queue_worker()


def start_queue_worker() -> None:
    global _thread
    if os.environ.get("CHARACTEROS_DISABLE_QUEUE_WORKER") == "1":
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_loop, name="characteros-queue-worker", daemon=True)
        _thread.start()
        logger.info("CharacterOS sequential queue worker started")


def _process_one() -> dict[str, Any] | None:
    global _busy, _last_task_id, _last_status, _last_error
    from characteros.storage.db_availability import is_database_available
    from characteros.storage.local_characters import LocalCharacterService
    from characteros.storage.local_queue import LocalQueueManager

    with _lock:
        if _busy:
            return None
        if _local_paused():
            return None
        _busy = True
    try:
        if is_database_available():
            from characteros.models.database import SessionLocal
            from characteros.services.queue import QueueManager

            db = SessionLocal()
            try:
                task = QueueManager(db).process_next_pending()
                payload = None if task is None else task.to_dict()
            finally:
                db.close()
        else:
            payload = LocalQueueManager().process_next(character_service=LocalCharacterService())
        if payload is None:
            _last_status = None
            return None
        _last_task_id = int(payload.get("id") or 0) or None
        _last_status = str(payload.get("status") or "")
        _last_error = payload.get("error_message")
        return payload
    except Exception as exc:
        logger.exception("Sequential queue worker failed: %s", exc)
        _last_error = str(exc)
        _last_status = "failed"
        return None
    finally:
        _busy = False


def _loop() -> None:
    while True:
        _wake.wait(timeout=8)
        _wake.clear()
        while not _local_paused():
            task = _process_one()
            if task is None:
                break
            if str(task.get("status") or "") == "failed":
                logger.warning(
                    "Queue worker stopped current pipeline at task #%s: %s",
                    task.get("id"),
                    task.get("error_message"),
                )
                break
