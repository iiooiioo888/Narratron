"""單一佇列任務的生圖執行（local / DB 共用）。

人物圖像生成主流程：

1. **入列** — `image_pipeline.enqueue_character_images`
   - 按需：只建立請求歲數的下一步（預設 face_detail）
   - fill_span：才依區間逐步銜接
2. **協調** — `pipeline_coordinator`
   - 上一步入庫後才動態入列下一步；同時最多一筆 pending
3. **執行** — 本模組 `run_queued_image_generation`
   - 查 character_variants 快取 → 收集參考圖 → ImagingService → 品質閘門
4. **worker** — `queue_worker`
   - 後端一次只 process 一筆；失敗暫停，等「重設失敗並繼續」
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from characteros.imaging.settings import settings as imaging_settings
from characteros.services.age_span import AgeSpanDependencyPending, prepare_queued_image_generation
from characteros.services.imaging import ImagingService
from characteros.services.quality_gate import evaluate_generation, max_quality_retries, quality_gate_enabled
from characteros.services.queue_task_utils import (
    apply_auto_accept,
    build_image_result_metadata,
    effective_task_status,
)
from characteros.services.variant_processor import (
    evolve_manifest,
    extract_image_request,
    sanitize_evolution_params,
    utcnow_iso,
)
from narratron.charpass.store import CharpassStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImagingCredentials:
    provider_name: str
    model: str
    base_url: str
    api_key: str


def resolve_imaging_credentials(image_request: dict[str, Any]) -> ImagingCredentials:
    """從任務請求與全域設定解析 provider / model / endpoint。"""
    provider_name = str(image_request.get("provider") or imaging_settings.get_provider() or "null")
    explicit_model = str(image_request.get("model") or "").strip()
    explicit_base_url = str(image_request.get("base_url") or "").strip()
    explicit_api_key = str(image_request.get("api_key") or "").strip()
    use_defaults = provider_name != "null"
    return ImagingCredentials(
        provider_name=provider_name,
        model=explicit_model or ("" if not use_defaults else str(imaging_settings.get_model() or "")),
        base_url=explicit_base_url or ("" if not use_defaults else str(imaging_settings.get_base_url() or "")),
        api_key=explicit_api_key or ("" if not use_defaults else str(imaging_settings.get_api_key() or "")),
    )


def run_queued_image_generation(
    *,
    evolved_manifest: dict[str, Any],
    image_request: dict[str, Any],
    sibling_tasks: list[dict[str, Any]],
    persist_entity_id: str | None,
    store: CharpassStore | None = None,
) -> dict[str, Any]:
    """依佇列任務執行生圖；年齡軸會自動收集參考圖與鎖定連貫性。"""
    generation_options = prepare_queued_image_generation(
        evolved_manifest,
        image_request,
        sibling_tasks=sibling_tasks,
    )
    credentials = resolve_imaging_credentials(image_request)
    service = ImagingService(store=store) if store is not None else ImagingService()
    return service.generate_for_manifest(
        evolved_manifest,
        purpose=str(image_request.get("purpose") or "identity"),
        provider_name=credentials.provider_name,
        extra=str(generation_options.get("extra") or image_request.get("extra") or ""),
        n=int(image_request.get("n") or 1),
        model=credentials.model,
        base_url=credentials.base_url,
        api_key=credentials.api_key,
        persist_entity_id=persist_entity_id,
        multi_angle=bool(generation_options.get("multi_angle", image_request.get("multi_angle", True))),
        auto_accept=True,
        extra_ref_uris=list(generation_options.get("extra_ref_uris") or []),
        extra_fields=dict(generation_options.get("extra_fields") or {}),
    )


def build_auto_accepted_task_result(
    *,
    core_id: int,
    payload: dict[str, Any],
    image_request: dict[str, Any],
    credentials: ImagingCredentials,
    persist_entity_id: str | None,
    processed_at: str,
) -> tuple[str, dict[str, Any], list[str]]:
    """組 result_url / metadata，並標記 auto_accept。"""
    result_url, result_metadata, image_urls = build_image_result_metadata(
        core_id=core_id,
        payload=payload,
        image_request=image_request,
        provider_name=credentials.provider_name,
        explicit_model=str(image_request.get("model") or "").strip(),
        persist_entity_id=persist_entity_id,
        processed_at=processed_at,
    )
    apply_auto_accept(result_metadata)
    return result_url, result_metadata, image_urls


def persist_auto_accepted_manifest(
    payload: dict[str, Any],
    save_fn: Callable[[dict[str, Any]], None],
) -> None:
    """生圖已 auto_accept 時寫回護照；失敗只記 log，不讓任務整體失敗。"""
    if str(payload.get("review_status") or "") != "accepted":
        return
    manifest = payload.get("manifest")
    if not isinstance(manifest, dict):
        return
    try:
        save_fn(manifest)
    except OSError as exc:
        logger.warning("生圖已入庫，略過二次寫入護照：%s", exc)


def _parse_started_at(value: Any, *, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return fallback


@dataclass
class ImageQueueExecution:
    """單一佇列任務生圖所需的上下文（local / DB 共用）。"""

    core_id: int
    task_id: int
    character_name: str
    raw_evolution_params: dict[str, Any]
    sibling_tasks: list[dict[str, Any]]
    base_manifest: dict[str, Any]
    entity_id: str | None = None
    store: CharpassStore | None = None
    output_dir: str | None = None
    variant_hash: str | None = None
    save_manifest: Callable[[dict[str, Any]], None] | None = None
    created_at: Any = None


@dataclass
class ImageQueueExecutionResult:
    """生圖執行結果，供 local JSON 或 ORM 寫回。"""

    status: str
    result_url: str | None
    result_metadata: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    review_status: str | None = None
    effective_status: str | None = None
    provider: str | None = None
    model: str | None = None
    queue_wait_ms: int = 0
    generation_duration_ms: int = 0
    record_patch: dict[str, Any] = field(default_factory=dict)


def execute_image_queue_task(context: ImageQueueExecution) -> ImageQueueExecutionResult:
    """執行單一佇列任務的生圖核心邏輯（local / DB 共用）。

    流程：evolve manifest → ImagingService → auto_accept → 組 result metadata。
    年齡軸依賴未就緒時回傳 status=waiting，不標記 failed。
    """
    started_at = datetime.now(timezone.utc)
    created_at = _parse_started_at(context.created_at, fallback=started_at)
    params = sanitize_evolution_params(context.raw_evolution_params or {})
    image_request = extract_image_request(context.raw_evolution_params or {})
    evolved_manifest = evolve_manifest(context.base_manifest, params)

    result_metadata: dict[str, Any] = {
        "evolved_manifest": evolved_manifest,
        "evolution_params": params,
    }
    if context.entity_id:
        result_metadata["entity_id"] = context.entity_id
    if context.output_dir:
        result_metadata["output_dir"] = context.output_dir
        result_metadata["record_path"] = f"{context.output_dir}/record.json"
        result_metadata["evolved_manifest_path"] = f"{context.output_dir}/evolved-manifest.json"

    record_patch: dict[str, Any] = {
        "task_id": int(context.task_id),
        "core_id": int(context.core_id),
        "character_name": context.character_name,
        "variant_hash": context.variant_hash,
        "status": "ready",
        "processed_at": utcnow_iso(),
        "evolution_params": params,
    }

    if context.store and context.entity_id and context.output_dir:
        context.store.write_json(
            context.entity_id,
            f"{context.output_dir}/evolved-manifest.json",
            evolved_manifest,
        )
        context.store.write_json(context.entity_id, f"{context.output_dir}/record.json", record_patch)

    try:
        result_url = (
            f"/api/v1/characters/{context.core_id}/assets/{context.output_dir}/evolved-manifest.json"
            if context.output_dir
            else f"/api/v1/characters/{context.core_id}/variants"
        )

        if image_request:
            persist_enabled = bool(image_request.get("persist", True))
            persist_entity_id = context.entity_id if persist_enabled else None
            credentials = resolve_imaging_credentials(image_request)
            attempts = max_quality_retries(image_request)
            payload: dict[str, Any] | None = None
            quality_report = None
            last_quality_reason = None
            for attempt in range(1, attempts + 1):
                payload = run_queued_image_generation(
                    evolved_manifest=evolved_manifest,
                    image_request=image_request,
                    sibling_tasks=context.sibling_tasks,
                    persist_entity_id=persist_entity_id,
                    store=context.store,
                )
                if not quality_gate_enabled():
                    break
                quality_report = evaluate_generation(
                    payload,
                    extra_ref_uris=list(payload.get("ref_image_uris") or []) if isinstance(payload, dict) else None,
                    provider_name=credentials.provider_name,
                )
                result_metadata["quality_gate"] = quality_report.to_dict()
                result_metadata["quality_score"] = quality_report.quality_score
                result_metadata["face_similarity"] = quality_report.face_similarity
                if quality_report.passed:
                    break
                last_quality_reason = quality_report.reason
                logger.warning(
                    "Quality gate failed for task #%s (attempt %s/%s): %s",
                    context.task_id,
                    attempt,
                    attempts,
                    quality_report.reason,
                )
            else:
                finished_at = datetime.now(timezone.utc)
                result_metadata["processed_at"] = finished_at.isoformat()
                return ImageQueueExecutionResult(
                    status="failed",
                    result_url=None,
                    result_metadata=result_metadata,
                    error_message=f"quality gate failed: {last_quality_reason or 'unknown'}",
                    queue_wait_ms=max(0, int((started_at - created_at).total_seconds() * 1000)),
                    generation_duration_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
                    record_patch=record_patch,
                )

            if persist_enabled and context.save_manifest and isinstance(payload, dict):
                persist_auto_accepted_manifest(payload, context.save_manifest)

            if not isinstance(payload, dict):
                raise RuntimeError("image generation returned no payload")

            finished_at = datetime.now(timezone.utc)
            result_url, image_meta, _image_urls = build_auto_accepted_task_result(
                core_id=int(context.core_id),
                payload=payload,
                image_request=image_request,
                credentials=credentials,
                persist_entity_id=persist_entity_id,
                processed_at=finished_at.isoformat(),
            )
            result_metadata.update(image_meta)
            result_metadata["persist_entity_id"] = persist_entity_id
            result_metadata["processed_at"] = finished_at.isoformat()
            result_metadata["result_image_url"] = result_url
            if quality_report is not None:
                result_metadata["quality_gate"] = quality_report.to_dict()
                result_metadata["quality_score"] = quality_report.quality_score
                result_metadata["face_similarity"] = quality_report.face_similarity
            review_status = str(result_metadata.get("review_status") or "") or None
            effective_status = effective_task_status("ready", result_metadata)
            record_patch.update(
                {
                    "review_status": review_status,
                    "thumbnail_asset_path": result_metadata.get("thumbnail_asset_path"),
                    "face_detail_asset_path": result_metadata.get("face_detail_asset_path"),
                    "face_detail_count": result_metadata.get("face_detail_count") or 0,
                    "result_image_url": result_url,
                }
            )
            if context.store and context.entity_id and context.output_dir:
                context.store.write_json(
                    context.entity_id,
                    f"{context.output_dir}/record.json",
                    record_patch,
                )
        else:
            finished_at = datetime.now(timezone.utc)
            result_metadata["processed_at"] = finished_at.isoformat()
            review_status = None
            effective_status = effective_task_status("ready", result_metadata)

        queue_wait_ms = max(0, int((started_at - created_at).total_seconds() * 1000))
        generation_duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
        return ImageQueueExecutionResult(
            status="ready",
            result_url=result_url,
            result_metadata=result_metadata,
            error_message=None,
            review_status=review_status,
            effective_status=effective_status,
            provider=result_metadata.get("provider"),
            model=result_metadata.get("model"),
            queue_wait_ms=queue_wait_ms,
            generation_duration_ms=generation_duration_ms,
            record_patch=record_patch,
        )
    except AgeSpanDependencyPending as exc:
        return ImageQueueExecutionResult(
            status="waiting",
            result_url=None,
            result_metadata=result_metadata,
            error_message=None,
        )
    except Exception as exc:
        logger.exception("Image queue task #%s failed: %s", context.task_id, exc)
        return ImageQueueExecutionResult(
            status="failed",
            result_url=None,
            result_metadata=result_metadata,
            error_message=str(exc),
        )
