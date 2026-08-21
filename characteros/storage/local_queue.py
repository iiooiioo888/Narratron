"""本機變體佇列：PostgreSQL 不可用時寫入 data/charpasses/.characteros-queue.json。"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException, status

from characteros.services.imaging import finalize_reviewed_generation, sync_review_artifacts
from characteros.services.variant_processor import extract_image_request
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
from characteros.storage.local_characters import LocalCharacterService
from characteros.utils.hash import compute_variant_hash
from narratron.charpass.store import CharpassStore

logger = logging.getLogger(__name__)

QUEUE_FILENAME = ".characteros-queue.json"

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    key = str(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return _utcnow()


class LocalQueueManager:
    """以 JSON 檔持久化變體佇列（離線／測試用）。"""

    def __init__(self, root: str | Path | None = None) -> None:
        store = CharpassStore(root)
        self.root = store.root
        self._path = self.root / QUEUE_FILENAME
        self._lock = _lock_for(self._path)

    def _load(self, *, _retried: bool = False) -> dict[str, Any]:
        if not self._path.is_file():
            return {"next_id": 1, "tasks": [], "worker": {"paused": False}}
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("Queue JSON unreadable at %s: %s", self._path, exc)
            return {"next_id": 1, "tasks": [], "worker": {"paused": False}}
        if not raw.strip():
            # 原子寫入瞬間可能讀到空檔；勿當成損壞而搬移真資料
            if not _retried:
                return self._load(_retried=True)
            return {"next_id": 1, "tasks": [], "worker": {"paused": False}}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            if not _retried:
                return self._load(_retried=True)
            logger.error("Queue JSON unreadable at %s: %s", self._path, exc)
            corrupt = self._path.with_name(f"{self._path.name}.corrupt")
            try:
                # 保留既有 .corrupt 備份，避免競態覆蓋
                if corrupt.is_file():
                    stamped = self._path.with_name(
                        f"{self._path.name}.corrupt.{_utcnow().strftime('%Y%m%d%H%M%S')}"
                    )
                    self._path.replace(stamped)
                else:
                    self._path.replace(corrupt)
                logger.error("Moved unreadable queue file to backup")
            except OSError:
                pass
            return {"next_id": 1, "tasks": [], "worker": {"paused": False}}
        if not isinstance(data, dict):
            return {"next_id": 1, "tasks": [], "worker": {"paused": False}}
        data.setdefault("next_id", 1)
        data.setdefault("tasks", [])
        data.setdefault("worker", {"paused": False})
        if not isinstance(data["tasks"], list):
            data["tasks"] = []
        if not isinstance(data.get("worker"), dict):
            data["worker"] = {"paused": False}
        data["worker"].setdefault("paused", False)
        return data

    def get_worker_control(self) -> dict[str, Any]:
        worker = self._load().get("worker")
        if not isinstance(worker, dict):
            return {"paused": False}
        return {"paused": bool(worker.get("paused"))}

    def set_worker_paused(self, paused: bool) -> dict[str, Any]:
        data = self._load()
        data["worker"] = {"paused": bool(paused)}
        self._save(data)
        return {"paused": bool(paused)}

    @staticmethod
    def _normalize_task_ids(data: dict[str, Any]) -> bool:
        """消除重複任務 ID，並把 next_id 推到 max(id)+1。回傳是否有改動。"""
        tasks = data.get("tasks")
        if not isinstance(tasks, list):
            data["tasks"] = []
            data["next_id"] = max(1, int(data.get("next_id") or 1))
            return True

        changed = False
        used: set[int] = set()
        cursor = 1
        for task in tasks:
            if not isinstance(task, dict):
                continue
            try:
                tid = int(task.get("id") or 0)
            except (TypeError, ValueError):
                tid = 0
            if tid <= 0 or tid in used:
                while cursor in used:
                    cursor += 1
                task["id"] = cursor
                tid = cursor
                changed = True
            used.add(tid)
            cursor = max(cursor, tid + 1)

        next_id = max(int(data.get("next_id") or 1), cursor)
        if int(data.get("next_id") or 1) != next_id:
            data["next_id"] = next_id
            changed = True
        else:
            data["next_id"] = next_id
        return changed

    def _save(self, data: dict[str, Any], *, allow_empty_tasks: bool = False) -> None:
        """Atomic write。入列可能已在磁碟推進 next_id；寫回前必須取較大值，避免覆寫成重複 ID。"""
        from characteros.utils.files import write_text_atomic

        self._normalize_task_ids(data)
        try:
            if self._path.is_file():
                on_disk_raw = self._path.read_text(encoding="utf-8")
                if on_disk_raw.strip():
                    on_disk = json.loads(on_disk_raw)
                    if isinstance(on_disk, dict):
                        data["next_id"] = max(
                            int(data.get("next_id") or 1),
                            int(on_disk.get("next_id") or 1),
                        )
                        disk_tasks = on_disk.get("tasks") if isinstance(on_disk.get("tasks"), list) else []
                        # 防止競態 _load 到空佇列後寫回，把進行中的任務整個抹掉
                        if (
                            not allow_empty_tasks
                            and not (data.get("tasks") or [])
                            and disk_tasks
                        ):
                            logger.error(
                                "Refusing to overwrite queue with empty tasks "
                                "(disk has %s tasks); keeping disk tasks",
                                len(disk_tasks),
                            )
                            data["tasks"] = disk_tasks
                        self._normalize_task_ids(data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        write_text_atomic(self._path, payload)

    def _load_index(self) -> dict[str, Any]:
        index_path = self.root / ".characteros-index.json"
        if not index_path.is_file():
            return {"next_id": 1, "entities": {}, "reverse": {}}
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"next_id": 1, "entities": {}, "reverse": {}}
        if not isinstance(data, dict):
            return {"next_id": 1, "entities": {}, "reverse": {}}
        return data

    def _entity_id_for_core_id(self, core_id: int) -> str:
        index = self._load_index()
        entity_id = (index.get("entities") or {}).get(str(core_id))
        if not entity_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character core {core_id} not found (local mode)",
            )
        return str(entity_id)

    def request_variant_generation(
        self,
        core_id: int,
        evolution_params: dict[str, Any],
        priority: int = 0,
        profile_version: int = 1,
        character_name: str | None = None,
        status: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """排入或回傳既有任務；回傳 (task_dict, is_new)。"""
        variant_hash = compute_variant_hash(core_id, profile_version, evolution_params)
        with self._lock:
            data = self._load()
            tasks: list[dict[str, Any]] = data["tasks"]

            for task in tasks:
                if task.get("core_id") == core_id and task.get("variant_hash") == variant_hash:
                    logger.info(
                        "Local variant already queued: core_id=%s hash=%s status=%s",
                        core_id,
                        variant_hash[:16],
                        task.get("status"),
                    )
                    return task, False

            now = _utcnow().isoformat()
            task_id = int(data.get("next_id") or 1)
            data["next_id"] = task_id + 1
            task = {
                "id": task_id,
                "core_id": core_id,
                "character_name": character_name,
                "profile_version": profile_version,
                "variant_hash": variant_hash,
                "evolution_params": evolution_params,
                "status": str(status or "pending").strip() or "pending",
                "priority": priority,
                "result_url": None,
                "result_metadata": {},
                "error_message": None,
                "retry_count": 0,
                "max_retries": 3,
                "queue_wait_ms": None,
                "generation_duration_ms": None,
                "created_at": now,
                "updated_at": now,
            }
            tasks.append(task)
            data["tasks"] = tasks
            self._save(data)
        logger.info("Local variant queued: id=%s core_id=%s", task_id, core_id)
        return task, True

    def get_task_by_id(self, task_id: int) -> Optional[dict[str, Any]]:
        for task in self._load()["tasks"]:
            if int(task.get("id", 0)) == task_id:
                return task
        return None

    @staticmethod
    def _select_task(
        tasks: list[dict[str, Any]],
        task_id: int,
        *,
        variant_hash: str | None = None,
    ) -> Optional[dict[str, Any]]:
        """依 id 找任務；重複 id 時優先 runnable，並可用 variant_hash 消歧。"""
        matches = [
            item for item in tasks if int(item.get("id", 0)) == int(task_id)
        ]
        if not matches:
            return None
        if variant_hash:
            hashed = [
                item
                for item in matches
                if str(item.get("variant_hash") or "") == str(variant_hash)
            ]
            if hashed:
                matches = hashed
        preferred_statuses = {"pending", "failed", "running"}
        preferred = [
            item
            for item in matches
            if str(item.get("status") or "").strip().lower() in preferred_statuses
        ]
        if preferred:
            return preferred[0]
        return matches[0]

    def _resync_after_nested_enqueue(self, data: dict[str, Any]) -> None:
        """request_variant_generation 會另一次 _load/寫盤；外層必須重載，否則 _save 會蓋掉新任務。"""
        fresh = self._load()
        data["next_id"] = int(fresh.get("next_id") or data.get("next_id") or 1)
        data["tasks"][:] = list(fresh.get("tasks") or [])
        worker = fresh.get("worker")
        if isinstance(worker, dict):
            data["worker"] = worker

    def process_task(
        self,
        task_id: int,
        *,
        character_service: LocalCharacterService | None = None,
        variant_hash: str | None = None,
    ) -> dict[str, Any]:
        """處理單一任務並把結果落到角色資料夾。"""
        with self._lock:
            data = self._load()
            tasks: list[dict[str, Any]] = data["tasks"]
            from characteros.services.age_span import (
                RUNNING_STATUS,
                has_in_flight_generation,
                recover_stale_running_tasks,
            )

            recover_stale_running_tasks(tasks)
            task = self._select_task(tasks, task_id, variant_hash=variant_hash)
            if not task:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Queue task {task_id} not found",
                )
            if str(task.get("status") or "") == "ready":
                return task
            current_status = str(task.get("status") or "").strip().lower()
            others_in_flight = [
                item
                for item in tasks
                if item is not task
                and str(item.get("status") or "").strip().lower() == RUNNING_STATUS
            ]
            if others_in_flight or (has_in_flight_generation(tasks) and current_status != RUNNING_STATUS):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="已有一張圖正在生成，生圖迴圈一次只允許一張",
                )
            if current_status not in {"pending", "failed", RUNNING_STATUS}:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Task {task_id} is {current_status or 'unknown'}, not runnable",
                )
            now = _utcnow().isoformat()
            task["status"] = RUNNING_STATUS
            task["started_at"] = now
            task["updated_at"] = now
            self._save(data)
            core_id = int(task["core_id"])
            raw_evolution_params = task.get("evolution_params") or {}
            locked_variant_hash = str(task.get("variant_hash") or variant_hash or "")
            created_at = task.get("created_at")
            stored_name = task.get("character_name")
            sibling_tasks = [
                item for item in tasks if int(item.get("core_id", 0)) == core_id
            ]
            locked_task_id = int(task.get("id") or task_id)

        service = character_service or LocalCharacterService(self.root)
        entity_id = self._entity_id_for_core_id(core_id)
        output_dir = f"causal/variants/{locked_task_id}"
        full = service.get_character_by_id(core_id)
        base_manifest = full.profile.manifest if full.profile else {}
        character_name = stored_name or full.core.name
        store = CharpassStore(self.root)

        outcome = execute_image_queue_task(
            ImageQueueExecution(
                core_id=core_id,
                task_id=int(locked_task_id),
                character_name=str(character_name),
                raw_evolution_params=raw_evolution_params,
                sibling_tasks=sibling_tasks,
                base_manifest=base_manifest,
                entity_id=entity_id,
                store=store,
                output_dir=output_dir,
                variant_hash=locked_variant_hash,
                save_manifest=lambda manifest: service.save_charpass(
                    core_id,
                    manifest,
                    snapshot_history=False,
                ),
                created_at=created_at,
            )
        )

        with self._lock:
            data = self._load()
            tasks = data["tasks"]
            task = self._select_task(
                tasks,
                locked_task_id,
                variant_hash=locked_variant_hash or None,
            )
            if not task:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Queue task {locked_task_id} not found",
                )
            task["character_name"] = character_name
            task["status"] = outcome.status
            task["result_metadata"] = outcome.result_metadata
            task["error_message"] = outcome.error_message
            task["review_status"] = outcome.review_status
            task["effective_status"] = outcome.effective_status
            task["provider"] = outcome.provider
            task["model"] = outcome.model
            task["queue_wait_ms"] = outcome.queue_wait_ms
            task["generation_duration_ms"] = outcome.generation_duration_ms
            if outcome.result_url:
                task["result_url"] = outcome.result_url
            if outcome.status == "failed":
                task["retry_count"] = int(task.get("retry_count") or 0) + 1
            task["updated_at"] = _utcnow().isoformat()

            if outcome.status == "ready":
                sync_age_span_task_states(tasks)

            self._save(data)
            if outcome.status == "ready":
                after_image_task_succeeded(
                    data["tasks"],
                    enqueue=self.request_variant_generation,
                    core_id=core_id or None,
                    reload_tasks=lambda: self._load()["tasks"],
                )
                self._resync_after_nested_enqueue(data)
                sync_age_span_task_states(data["tasks"])
                self._save(data)
            return task

    def review_task(
        self,
        task_id: int,
        *,
        accepted: bool,
        character_service: LocalCharacterService | None = None,
    ) -> dict[str, Any]:
        """人工接受或拒絕已完成的生圖任務。"""
        with self._lock:
            return self._review_task_body(
                task_id, accepted=accepted, character_service=character_service
            )

    def _review_task_body(
        self,
        task_id: int,
        *,
        accepted: bool,
        character_service: LocalCharacterService | None = None,
    ) -> dict[str, Any]:
        data = self._load()
        tasks: list[dict[str, Any]] = data["tasks"]
        task = next((item for item in tasks if int(item.get("id", 0)) == int(task_id)), None)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Queue task {task_id} not found",
            )

        if str(task.get("status") or "") != "ready":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only ready tasks can be reviewed",
            )

        image_generation = (
            task.get("result_metadata", {}).get("image_generation")
            if isinstance(task.get("result_metadata"), dict)
            else None
        )
        if not isinstance(image_generation, dict):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This task has no image generation result to review",
            )

        review = image_generation.get("review") if isinstance(image_generation.get("review"), dict) else {}
        current_status = str(review.get("status") or "").strip() or "pending"
        if current_status == "accepted" and accepted:
            return task
        if current_status == "accepted" and not accepted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Accepted tasks cannot be rejected after publish",
            )
        if current_status == "rejected" and not accepted:
            return task

        if accepted:
            service = character_service or LocalCharacterService(self.root)
            entity_id = str(
                task.get("result_metadata", {}).get("persist_entity_id")
                or review.get("entity_id")
                or ""
            ).strip()
            if not entity_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This task has no staged assets to accept",
                )
            promoted = finalize_reviewed_generation(entity_id, image_generation, store=CharpassStore(self.root))
            service.save_charpass(int(task["core_id"]), promoted["manifest"])
            promoted_payload = promoted["payload"]
            image_generation.update(promoted_payload)
            task["result_url"], _, _image_urls = build_image_result_metadata(
                core_id=int(task["core_id"]),
                payload=image_generation,
                image_request={},
                provider_name=str(image_generation.get("provider") or ""),
                explicit_model=str(image_generation.get("model") or ""),
                persist_entity_id=entity_id or None,
                processed_at=_utcnow().isoformat(),
            )
        else:
            review["status"] = "rejected"
            review["rejected_at"] = _utcnow().isoformat()
            image_generation["review"] = review
        entity_id = str(
            task.get("result_metadata", {}).get("persist_entity_id")
            or review.get("entity_id")
            or ""
        ).strip()
        if entity_id:
            sync_review_artifacts(entity_id, image_generation, store=CharpassStore(self.root))

        apply_review_metadata(task["result_metadata"], image_generation)
        task["result_metadata"]["effective_status"] = effective_task_status(
            task.get("status"),
            task["result_metadata"],
        )
        task["review_status"] = task["result_metadata"].get("review_status")
        task["effective_status"] = task["result_metadata"].get("effective_status")
        variant_record_path = task["result_metadata"].get("record_path")
        if entity_id and isinstance(variant_record_path, str) and variant_record_path.strip():
            variant_record = CharpassStore(self.root).read_json(entity_id, variant_record_path)
            if not isinstance(variant_record, dict):
                variant_record = {}
            review_status = task["result_metadata"].get("review_status")
            record_status = "accepted" if review_status == "accepted" else "rejected" if review_status == "rejected" else "ready"
            variant_record.update(
                {
                    "status": record_status,
                    "review_status": review_status,
                    "accepted_at": review.get("accepted_at"),
                    "rejected_at": review.get("rejected_at"),
                    "thumbnail_asset_path": task["result_metadata"].get("thumbnail_asset_path"),
                    "face_detail_asset_path": task["result_metadata"].get("face_detail_asset_path"),
                    "face_detail_count": task["result_metadata"].get("face_detail_count") or 0,
                }
            )
            CharpassStore(self.root).write_json(entity_id, variant_record_path, variant_record)
        task["updated_at"] = _utcnow().isoformat()
        self._save(data)
        return task

    def reset_failed_tasks(
        self,
        *,
        core_id: int | None = None,
        from_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """將 failed 任務重設為 pending，以便逐筆重試。"""
        with self._lock:
            data = self._load()
            tasks: list[dict[str, Any]] = data["tasks"]
            reset: list[dict[str, Any]] = []
            now = _utcnow().isoformat()
            for task in tasks:
                if str(task.get("status") or "").strip().lower() != "failed":
                    continue
                if core_id is not None and int(task.get("core_id", 0)) != int(core_id):
                    continue
                if from_id is not None and int(task.get("id", 0)) < int(from_id):
                    continue
                task["status"] = "waiting"
                task["error_message"] = None
                task["updated_at"] = now
                reset.append(task)
            if reset:
                sync_age_span_task_states(data["tasks"])
                self._save(data)
            return reset

    def clear_tasks(self, *, core_id: int | None = None) -> int:
        """清空佇列任務；可選只清除指定角色的任務。"""
        with self._lock:
            data = self._load()
            tasks: list[dict[str, Any]] = data["tasks"]
            if core_id is None:
                removed = len(tasks)
                data["tasks"] = []
            else:
                kept = [task for task in tasks if int(task.get("core_id", 0)) != int(core_id)]
                removed = len(tasks) - len(kept)
                data["tasks"] = kept
            if removed:
                self._save(data, allow_empty_tasks=True)
            return removed

    def reset_task_to_pending(self, task_id: int) -> dict[str, Any]:
        """將單一 failed 任務重設為 pending。"""
        data = self._load()
        tasks: list[dict[str, Any]] = data["tasks"]
        task = next((item for item in tasks if int(item.get("id", 0)) == int(task_id)), None)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Queue task {task_id} not found",
            )
        if str(task.get("status") or "").strip().lower() != "failed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only failed tasks can be reset to pending",
            )
        task["status"] = "waiting"
        task["error_message"] = None
        task["updated_at"] = _utcnow().isoformat()
        sync_age_span_task_states(data["tasks"])
        self._save(data)
        return task

    def normalize_age_span_statuses(self) -> None:
        data = self._load()
        sync_age_span_task_states(data["tasks"])
        self._save(data)

    def ensure_following_age_span_tasks(self, *, core_id: int | None = None) -> list[dict[str, Any]]:
        """年齡軸完成一步後，只再排入下一步，避免一次塞滿 1–80 歲任務。"""
        with self._lock:
            data = self._load()
            created = after_image_task_succeeded(
                data["tasks"],
                enqueue=self.request_variant_generation,
                core_id=core_id,
                wake_worker=False,
                reload_tasks=lambda: self._load()["tasks"],
            )
            self._resync_after_nested_enqueue(data)
            sync_age_span_task_states(data["tasks"])
            self._save(data)
            return created

    def repair_task_ids(self) -> dict[str, Any]:
        """掃描並修復重複任務 ID / next_id，寫回磁碟。"""
        with self._lock:
            data = self._load()
            before_ids = [
                int(t.get("id") or 0) for t in (data.get("tasks") or []) if isinstance(t, dict)
            ]
            changed = self._normalize_task_ids(data)
            # 即使 next_id 已對，只要 id 有重號就一定要寫回
            if changed or len(before_ids) != len(set(before_ids)):
                self._save(data)
                changed = True
            return {
                "changed": changed,
                "next_id": int(data.get("next_id") or 1),
                "task_count": len(data.get("tasks") or []),
                "task_ids": [
                    int(t.get("id") or 0) for t in (data.get("tasks") or []) if isinstance(t, dict)
                ],
            }

    def process_next(
        self,
        *,
        character_service: LocalCharacterService | None = None,
        core_id: int | None = None,
    ) -> Optional[dict[str, Any]]:
        """處理下一筆可執行的 pending 任務（年齡軸依依賴逐步執行）。"""
        with self._lock:
            data = self._load()
            from characteros.services.pipeline_coordinator import prepare_for_processing

            prepare_for_processing(
                data["tasks"],
                enqueue=self.request_variant_generation,
                core_id=core_id,
            )
            # nested enqueue 寫的是另一份 list；不重載就 _save 會抹掉剛入列的任務
            self._resync_after_nested_enqueue(data)
            sync_age_span_task_states(data["tasks"])
            self._save(data)
            scoped = data["tasks"] if core_id is None else [
                item for item in data["tasks"] if int(item.get("core_id", 0)) == int(core_id)
            ]
            runnable = find_next_runnable_task(scoped)
            runnable_id = int(runnable["id"]) if runnable else None
            runnable_hash = str(runnable.get("variant_hash") or "") if runnable else None
        if runnable_id is None:
            return None
        try:
            return self.process_task(
                runnable_id,
                character_service=character_service,
                variant_hash=runnable_hash or None,
            )
        except HTTPException as exc:
            if exc.status_code == status.HTTP_409_CONFLICT:
                return None
            raise

    def process_all(
        self,
        *,
        limit: int = 20,
        character_service: LocalCharacterService | None = None,
    ) -> list[dict[str, Any]]:
        """批次處理多筆 pending 任務（每次只處理當下可執行者）。"""
        processed: list[dict[str, Any]] = []
        max_count = max(1, min(limit, 200))
        for _ in range(max_count):
            task = self.process_next(character_service=character_service)
            if task is None:
                break
            processed.append(task)
        return processed

    def list_tasks(
        self,
        *,
        status: str | None = None,
        core_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        tasks = list(self._load()["tasks"])
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        if core_id is not None:
            tasks = [t for t in tasks if int(t.get("core_id", 0)) == core_id]
        for task in tasks:
            result_metadata = task.get("result_metadata") if isinstance(task.get("result_metadata"), dict) else {}
            task["review_status"] = review_status_from_metadata(result_metadata)
            task["effective_status"] = effective_task_status(task.get("status"), result_metadata)
        tasks.sort(
            key=lambda t: (
                -int(t.get("priority") or 0),
                t.get("created_at") or "",
            ),
        )
        return tasks[: max(1, min(limit, 400))]

    def get_queue_stats(self) -> dict[str, Any]:
        tasks = self._load()["tasks"]
        pending = [t for t in tasks if t.get("status") == "pending"]
        waiting = [t for t in tasks if t.get("status") == "waiting"]
        running = [t for t in tasks if t.get("status") == "running"]
        ready = [t for t in tasks if t.get("status") == "ready"]
        failed = [t for t in tasks if t.get("status") == "failed"]

        waits = [
            float(t["queue_wait_ms"])
            for t in tasks
            if t.get("queue_wait_ms") is not None
        ]
        avg_wait = sum(waits) / len(waits) if waits else 0.0

        oldest_age = 0.0
        if pending:
            oldest = min(_parse_dt(t.get("created_at")) for t in pending)
            oldest_age = (_utcnow() - oldest).total_seconds()

        return {
            "total_pending": len(pending),
            "total_waiting": len(waiting),
            "total_running": len(running),
            "total_ready": len(ready),
            "total_failed": len(failed),
            "average_wait_time_ms": avg_wait,
            "oldest_pending_age_seconds": oldest_age,
        }

    def ensure_character_exists(self, core_id: int, character_name: str | None = None) -> None:
        """若 core_id 不在 index 中仍允許排隊，但可選驗證角色存在。"""
        if character_name:
            return
        index_path = self.root / ".characteros-index.json"
        if not index_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character core {core_id} not found (local mode)",
            )
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character core {core_id} not found (local mode)",
            )
        reverse = index.get("reverse") or {}
        if str(core_id) not in reverse:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character core {core_id} not found (local mode)",
            )
