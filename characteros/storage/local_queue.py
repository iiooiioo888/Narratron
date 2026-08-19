"""本機變體佇列：PostgreSQL 不可用時寫入 data/charpasses/.characteros-queue.json。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException, status

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
        if not isinstance(data["tasks"], list):
            data["tasks"] = []
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def request_variant_generation(
        self,
        core_id: int,
        evolution_params: dict[str, Any],
        priority: int = 0,
        profile_version: int = 1,
        character_name: str | None = None,
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
            "status": "pending",
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
        tasks.sort(
            key=lambda t: (
                -int(t.get("priority") or 0),
                t.get("created_at") or "",
            ),
        )
        return tasks[: max(1, min(limit, 200))]

    def get_queue_stats(self) -> dict[str, Any]:
        tasks = self._load()["tasks"]
        pending = [t for t in tasks if t.get("status") == "pending"]
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
