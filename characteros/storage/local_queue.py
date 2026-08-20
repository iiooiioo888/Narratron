"""本機變體佇列：PostgreSQL 不可用時寫入 data/charpasses/.characteros-queue.json。"""

from __future__ import annotations

import json
import logging
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

    def _load(self) -> dict[str, Any]:
        if not self._path.is_file():
            return {"next_id": 1, "tasks": []}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"next_id": 1, "tasks": []}
        if not isinstance(data, dict):
            return {"next_id": 1, "tasks": []}
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

    def _save(self, data: dict[str, Any]) -> None:
        """Atomic write：先寫暫存檔再 rename，避免中途 crash 導致 JSON 損壞。"""
        self.root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        tmp = self._path.with_name(f"{self._path.name}.tmp")
        try:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            # fallback: 直接寫入（tmp 可能因跨 filesystem 無法 rename）
            try:
                self._path.write_text(payload, encoding="utf-8")
            finally:
                tmp.unlink(missing_ok=True)

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

    def process_task(
        self,
        task_id: int,
        *,
        character_service: LocalCharacterService | None = None,
    ) -> dict[str, Any]:
        """處理單一任務並把結果落到角色資料夾。"""
        data = self._load()
        tasks: list[dict[str, Any]] = data["tasks"]
        task = next((item for item in tasks if int(item.get("id", 0)) == int(task_id)), None)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Queue task {task_id} not found",
            )
        if str(task.get("status") or "") == "ready":
            return task

        service = character_service or LocalCharacterService(self.root)
        entity_id = self._entity_id_for_core_id(int(task["core_id"]))
        output_dir = f"causal/variants/{task['id']}"
        full = service.get_character_by_id(int(task["core_id"]))
        base_manifest = full.profile.manifest if full.profile else {}
        character_name = task.get("character_name") or full.core.name
        sibling_tasks = [
            item for item in tasks if int(item.get("core_id", 0)) == int(task["core_id"])
        ]
        store = CharpassStore(self.root)

        outcome = execute_image_queue_task(
            ImageQueueExecution(
                core_id=int(task["core_id"]),
                task_id=int(task["id"]),
                character_name=str(character_name),
                raw_evolution_params=task.get("evolution_params") or {},
                sibling_tasks=sibling_tasks,
                base_manifest=base_manifest,
                entity_id=entity_id,
                store=store,
                output_dir=output_dir,
                variant_hash=str(task.get("variant_hash") or ""),
                save_manifest=lambda manifest: service.save_charpass(
                    int(task["core_id"]),
                    manifest,
                    snapshot_history=False,
                ),
                created_at=task.get("created_at"),
            )
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
            data = self._load()
            after_image_task_succeeded(
                data["tasks"],
                enqueue=self.request_variant_generation,
                core_id=int(task.get("core_id") or 0) or None,
                reload_tasks=lambda: self._load()["tasks"],
            )
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
            review["rejected_at"] = utcnow_iso()
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
            data = self._load()
            sync_age_span_task_states(data["tasks"])
            self._save(data)
        return reset

    def clear_tasks(self, *, core_id: int | None = None) -> int:
        """清空佇列任務；可選只清除指定角色的任務。"""
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
            self._save(data)
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
        data = self._load()
        created = after_image_task_succeeded(
            data["tasks"],
            enqueue=self.request_variant_generation,
            core_id=core_id,
            wake_worker=False,
            reload_tasks=lambda: self._load()["tasks"],
        )
        self._save(data)
        return created

    def process_next(
        self,
        *,
        character_service: LocalCharacterService | None = None,
        core_id: int | None = None,
    ) -> Optional[dict[str, Any]]:
        """處理下一筆可執行的 pending 任務（年齡軸依依賴逐步執行）。"""
        data = self._load()
        from characteros.services.pipeline_coordinator import prepare_for_processing

        prepare_for_processing(
            data["tasks"],
            enqueue=self.request_variant_generation,
            core_id=core_id,
        )
        self._save(data)
        scoped = data["tasks"] if core_id is None else [
            item for item in data["tasks"] if int(item.get("core_id", 0)) == int(core_id)
        ]
        runnable = find_next_runnable_task(scoped)
        if not runnable:
            return None
        return self.process_task(
            int(runnable["id"]),
            character_service=character_service,
        )

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
