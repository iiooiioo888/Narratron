"""本機變體佇列：PostgreSQL 不可用時寫入 data/charpasses/.characteros-queue.json。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException, status

from characteros.imaging.settings import settings as imaging_settings
from characteros.services.imaging import (
    ImagingService,
    finalize_reviewed_generation,
    sync_review_artifacts,
)
from characteros.services.variant_processor import evolve_manifest, sanitize_evolution_params, utcnow_iso
from characteros.services.variant_processor import extract_image_request
from characteros.storage.local_characters import LocalCharacterService
from characteros.utils.hash import compute_variant_hash
from narratron.charpass.store import CharpassStore

logger = logging.getLogger(__name__)

QUEUE_FILENAME = ".characteros-queue.json"
PREFERRED_RESULT_ANGLES = (
    "face_detail",
    "front",
    "three_quarter",
    "left",
    "right",
    "back",
    "top",
    "bottom",
)


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


def _prepare_result_urls(core_id: int, payload: dict[str, Any]) -> tuple[str, list[str]]:
    images = payload.get("images") if isinstance(payload.get("images"), list) else []
    image_urls: list[str] = []
    representative_url: str | None = None
    for image in images:
        if not isinstance(image, dict):
            continue
        asset_path = str(image.get("asset_path") or "").strip()
        if asset_path:
            image_url = f"/api/v1/characters/{core_id}/assets/{asset_path}"
            image_urls.append(image_url)
            if representative_url is None:
                representative_url = image_url
    thumbnail_image = payload.get("thumbnail_image") if isinstance(payload.get("thumbnail_image"), dict) else {}
    thumbnail_asset_path = str(
        payload.get("thumbnail_asset_path")
        or thumbnail_image.get("asset_path")
        or ""
    ).strip()
    face_detail_asset_path = str(payload.get("face_detail_asset_path") or "").strip()
    representative_asset_path = face_detail_asset_path or thumbnail_asset_path
    if representative_asset_path:
        representative_url = f"/api/v1/characters/{core_id}/assets/{representative_asset_path}"
    else:
        for angle in PREFERRED_RESULT_ANGLES:
            for image in images:
                if not isinstance(image, dict):
                    continue
                if str(image.get("angle") or "").strip() != angle:
                    continue
                asset_path = str(image.get("asset_path") or "").strip()
                if asset_path:
                    representative_url = f"/api/v1/characters/{core_id}/assets/{asset_path}"
                    break
            if representative_url:
                break
    result_url = representative_url or (image_urls[0] if image_urls else f"/api/v1/characters/{core_id}/variants")
    return result_url, image_urls


def _apply_review_metadata(
    result_metadata: dict[str, Any],
    image_generation: dict[str, Any],
) -> None:
    review = image_generation.get("review") if isinstance(image_generation.get("review"), dict) else {}
    review_status = str(review.get("status") or "").strip() or None
    image_generation["review_status"] = review_status
    result_metadata["image_generation"] = image_generation
    result_metadata["thumbnail_asset_path"] = image_generation.get("thumbnail_asset_path")
    result_metadata["face_detail_asset_path"] = image_generation.get("face_detail_asset_path")
    result_metadata["face_detail_count"] = image_generation.get("face_detail_count") or 0
    result_metadata["review_status"] = review_status


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

        started_at = _utcnow()
        service = character_service or LocalCharacterService(self.root)
        entity_id = self._entity_id_for_core_id(int(task["core_id"]))
        output_dir = f"causal/variants/{task['id']}"

        try:
            full = service.get_character_by_id(int(task["core_id"]))
            base_manifest = full.profile.manifest if full.profile else {}
            raw_params = task.get("evolution_params") or {}
            params = sanitize_evolution_params(raw_params)
            image_request = extract_image_request(raw_params)
            evolved_manifest = evolve_manifest(base_manifest, params)

            store = CharpassStore(self.root)
            record = {
                "task_id": int(task["id"]),
                "core_id": int(task["core_id"]),
                "character_name": task.get("character_name") or full.core.name,
                "variant_hash": task.get("variant_hash"),
                "status": "ready",
                "processed_at": utcnow_iso(),
                "evolution_params": params,
            }
            store.write_json(entity_id, f"{output_dir}/evolved-manifest.json", evolved_manifest)
            store.write_json(entity_id, f"{output_dir}/record.json", record)

            finished_at = _utcnow()
            task["status"] = "ready"
            task["character_name"] = task.get("character_name") or full.core.name
            task["result_url"] = f"/api/v1/characters/{task['core_id']}/assets/{output_dir}/evolved-manifest.json"
            result_metadata = {
                "entity_id": entity_id,
                "output_dir": output_dir,
                "record_path": f"{output_dir}/record.json",
                "evolved_manifest_path": f"{output_dir}/evolved-manifest.json",
                "evolved_manifest": evolved_manifest,
                "processed_at": finished_at.isoformat(),
                "evolution_params": params,
            }
            if image_request:
                persist_enabled = bool(image_request.get("persist", True))
                payload = ImagingService(store=store).generate_for_manifest(
                    evolved_manifest,
                    purpose=str(image_request.get("purpose") or "identity"),
                    provider_name=str(image_request.get("provider") or imaging_settings.get_provider() or "null"),
                    extra=str(image_request.get("extra") or ""),
                    n=int(image_request.get("n") or 1),
                    model=str(image_request.get("model") or imaging_settings.get_model() or ""),
                    base_url=str(image_request.get("base_url") or imaging_settings.get_base_url() or ""),
                    api_key=str(image_request.get("api_key") or imaging_settings.get_api_key() or ""),
                    persist_entity_id=entity_id if persist_enabled else None,
                    multi_angle=bool(image_request.get("multi_angle", True)),
                    auto_accept=False,
                )
                task["result_url"], image_urls = _prepare_result_urls(int(task["core_id"]), payload)
                result_metadata["persist_entity_id"] = entity_id if persist_enabled else None
                result_metadata["thumbnail_asset_path"] = payload.get("thumbnail_asset_path")
                result_metadata["face_detail_asset_path"] = payload.get("face_detail_asset_path")
                result_metadata["face_detail_count"] = payload.get("face_detail_count") or 0
                result_metadata["image_request"] = image_request
                result_metadata["image_generation"] = {
                    "provider": payload.get("provider"),
                    "model": payload.get("model"),
                    "purpose": payload.get("purpose"),
                    "prompt": payload.get("prompt"),
                    "negative_prompt": payload.get("negative_prompt"),
                    "multi_angle": payload.get("multi_angle"),
                    "angles": payload.get("angles") or [],
                    "images": payload.get("images") or [],
                    "image_urls": image_urls,
                    "images_by_angle": payload.get("images_by_angle") or {},
                    "face_detail_images": payload.get("face_detail_images") or [],
                    "face_detail_asset_path": payload.get("face_detail_asset_path"),
                    "face_detail_count": payload.get("face_detail_count") or 0,
                    "thumbnail_image": payload.get("thumbnail_image"),
                    "thumbnail_asset_path": payload.get("thumbnail_asset_path"),
                    "review": payload.get("review") or {},
                    "review_status": (
                        (payload.get("review") or {}).get("status")
                        if isinstance(payload.get("review"), dict)
                        else None
                    ),
                }
                result_metadata["review_status"] = (
                    (payload.get("review") or {}).get("status")
                    if isinstance(payload.get("review"), dict)
                    else None
                )
                record.update(
                    {
                        "review_status": result_metadata["review_status"],
                        "thumbnail_asset_path": result_metadata.get("thumbnail_asset_path"),
                        "face_detail_asset_path": result_metadata.get("face_detail_asset_path"),
                        "face_detail_count": result_metadata.get("face_detail_count") or 0,
                    }
                )
                store.write_json(entity_id, f"{output_dir}/record.json", record)
            task["result_metadata"] = result_metadata
            task["error_message"] = None
            task["queue_wait_ms"] = max(
                0,
                int((started_at - _parse_dt(task.get("created_at"))).total_seconds() * 1000),
            )
            task["generation_duration_ms"] = max(
                0,
                int((finished_at - started_at).total_seconds() * 1000),
            )
            task["updated_at"] = finished_at.isoformat()
        except Exception as exc:
            task["status"] = "failed"
            task["retry_count"] = int(task.get("retry_count") or 0) + 1
            task["error_message"] = str(exc)
            task["updated_at"] = _utcnow().isoformat()

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
            task["result_url"], _image_urls = _prepare_result_urls(int(task["core_id"]), image_generation)
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

        _apply_review_metadata(task["result_metadata"], image_generation)
        variant_record_path = task["result_metadata"].get("record_path")
        if entity_id and isinstance(variant_record_path, str) and variant_record_path.strip():
            variant_record = CharpassStore(self.root).read_json(entity_id, variant_record_path)
            if not isinstance(variant_record, dict):
                variant_record = {}
            review_status = task["result_metadata"].get("review_status")
            variant_record.update(
                {
                    "status": "ready",
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

    def process_next(
        self,
        *,
        character_service: LocalCharacterService | None = None,
    ) -> Optional[dict[str, Any]]:
        """處理優先級最高且最早建立的 pending 任務。"""
        tasks = self.list_tasks(status="pending", limit=1)
        if not tasks:
            return None
        return self.process_task(
            int(tasks[0]["id"]),
            character_service=character_service,
        )

    def process_all(
        self,
        *,
        limit: int = 20,
        character_service: LocalCharacterService | None = None,
    ) -> list[dict[str, Any]]:
        """批次處理多筆 pending 任務。"""
        pending = self.list_tasks(status="pending", limit=max(1, min(limit, 200)))
        processed: list[dict[str, Any]] = []
        for task in pending:
            processed.append(
                self.process_task(
                    int(task["id"]),
                    character_service=character_service,
                )
            )
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
