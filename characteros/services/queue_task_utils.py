"""佇列任務共用工具：狀態判斷、結果 metadata、角度排序。"""

from __future__ import annotations

from typing import Any

from characteros.services.age_span import stamp_lock_url

PREFERRED_RESULT_ANGLES = (
    "face_detail",
    "tpose",
    "front",
    "three_quarter",
    "left",
    "right",
    "back",
    "top",
    "bottom",
)


def review_status_from_metadata(result_metadata: dict[str, Any]) -> str | None:
    image_generation = result_metadata.get("image_generation")
    if isinstance(image_generation, dict):
        review = image_generation.get("review")
        if isinstance(review, dict):
            status = str(review.get("status") or "").strip().lower()
            if status:
                return status
        status = str(image_generation.get("review_status") or "").strip().lower()
        if status:
            return status
    status = str(result_metadata.get("review_status") or "").strip().lower()
    return status or None


def has_generation_result(result_metadata: dict[str, Any]) -> bool:
    image_generation = (
        result_metadata.get("image_generation")
        if isinstance(result_metadata.get("image_generation"), dict)
        else {}
    )
    images = image_generation.get("images")
    if isinstance(images, list) and images:
        return True
    for key in ("face_detail_asset_path", "thumbnail_asset_path", "representative_asset_path"):
        if str(image_generation.get(key) or result_metadata.get(key) or "").strip():
            return True
    image_count = result_metadata.get("image_count") or image_generation.get("image_count")
    return bool(image_count)


def effective_task_status(status: Any, result_metadata: dict[str, Any]) -> str:
    """佇列任務對外顯示狀態；ready 且已有生圖結果時視同 accepted（自動入庫）。"""
    review_status = review_status_from_metadata(result_metadata)
    if review_status == "accepted":
        return "accepted"
    if review_status == "rejected":
        return "rejected"
    normalized_status = str(status or "").strip().lower()
    if normalized_status == "ready" and has_generation_result(result_metadata):
        return "accepted"
    if review_status == "pending":
        return "pending"
    return normalized_status or "pending"


def ordered_angles(values: list[Any], *, has_face_detail: bool = False) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    if has_face_detail:
        ordered.append("face_detail")
        seen.add("face_detail")
    for preferred in PREFERRED_RESULT_ANGLES:
        if preferred == "face_detail" and not has_face_detail:
            continue
        if any(str(value or "").strip() == preferred for value in values):
            ordered.append(preferred)
            seen.add(preferred)
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in seen:
            ordered.append(normalized)
            seen.add(normalized)
    if has_face_detail and "face_detail" not in seen:
        ordered.insert(0, "face_detail")
    return ordered


def apply_review_metadata(
    result_metadata: dict[str, Any],
    image_generation: dict[str, Any],
) -> None:
    """人工審核後，同步 review 狀態到 task result_metadata。"""
    review = image_generation.get("review") if isinstance(image_generation.get("review"), dict) else {}
    review_status = str(review.get("status") or "").strip() or None
    thumbnail_asset_path = str(image_generation.get("thumbnail_asset_path") or "").strip() or None
    face_detail_asset_path = str(image_generation.get("face_detail_asset_path") or "").strip() or None
    representative_asset_path = face_detail_asset_path or thumbnail_asset_path
    representative_angle = None
    if face_detail_asset_path:
        representative_angle = "face_detail"
    elif thumbnail_asset_path:
        representative_angle = next(
            (
                str(image.get("angle") or "").strip()
                for image in (image_generation.get("images") or [])
                if isinstance(image, dict)
                and str(image.get("asset_path") or "").strip() == thumbnail_asset_path
                and str(image.get("angle") or "").strip()
            ),
            "front",
        )
    angles = ordered_angles(
        list(image_generation.get("angles") or []),
        has_face_detail=bool(face_detail_asset_path),
    )
    image_generation["review_status"] = review_status
    image_generation["has_face_detail"] = bool(image_generation.get("face_detail_count") or face_detail_asset_path)
    image_generation["representative_asset_path"] = representative_asset_path
    image_generation["representative_angle"] = representative_angle
    image_generation["image_count"] = len(image_generation.get("image_urls") or [])
    result_metadata["image_generation"] = image_generation
    result_metadata["thumbnail_asset_path"] = thumbnail_asset_path
    result_metadata["face_detail_asset_path"] = face_detail_asset_path
    result_metadata["face_detail_count"] = image_generation.get("face_detail_count") or 0
    result_metadata["has_face_detail"] = bool(image_generation.get("face_detail_count") or face_detail_asset_path)
    result_metadata["representative_asset_path"] = representative_asset_path
    result_metadata["representative_angle"] = representative_angle
    result_metadata["review_status"] = review_status
    result_metadata["effective_status"] = effective_task_status("ready", result_metadata)
    result_metadata["purpose"] = image_generation.get("purpose")
    result_metadata["angles"] = angles
    result_metadata["image_count"] = len(image_generation.get("image_urls") or [])


def apply_auto_accept(result_metadata: dict[str, Any]) -> None:
    """生圖完成後自動標記為 accepted，並寫入 lock_url 供年齡軸下一步參考。"""
    if not has_generation_result(result_metadata):
        return
    result_metadata["review_status"] = "accepted"
    image_generation = (
        result_metadata.get("image_generation")
        if isinstance(result_metadata.get("image_generation"), dict)
        else {}
    )
    review_payload = (
        image_generation.get("review") if isinstance(image_generation.get("review"), dict) else {}
    )
    image_generation["review"] = {**review_payload, "status": "accepted", "auto_accept": True}
    image_generation["review_status"] = "accepted"
    result_metadata["image_generation"] = image_generation
    stamp_lock_url(result_metadata, result_metadata)
    result_metadata["effective_status"] = effective_task_status("ready", result_metadata)


def build_image_result_metadata(
    *,
    core_id: int,
    payload: dict[str, Any],
    image_request: dict[str, Any],
    provider_name: str,
    explicit_model: str,
    persist_entity_id: str | None,
    processed_at: str,
) -> tuple[str, dict[str, Any], list[str]]:
    """由 ImagingService payload 組出 result_url 與 result_metadata。"""
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
    review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    review_status = str(review.get("status") or "").strip() or None

    normalized_angles = ordered_angles(
        list(payload.get("angles") or []),
        has_face_detail=bool(face_detail_asset_path),
    )
    stored_provider = str(payload.get("provider") or provider_name or "").strip() or None
    stored_model = str(payload.get("model") or "").strip()
    if provider_name == "null" and not explicit_model:
        stored_model = "null"
    elif not stored_model:
        stored_model = explicit_model or None

    representative_asset_path = face_detail_asset_path or thumbnail_asset_path
    representative_angle = None
    if face_detail_asset_path:
        representative_angle = "face_detail"
    elif thumbnail_asset_path:
        representative_angle = next(
            (
                str(image.get("angle") or "").strip()
                for image in images
                if isinstance(image, dict)
                and str(image.get("asset_path") or "").strip() == thumbnail_asset_path
                and str(image.get("angle") or "").strip()
            ),
            "front",
        )
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

    result_url = representative_url or (
        image_urls[0] if image_urls else f"/api/v1/characters/{core_id}/variants"
    )
    result_metadata: dict[str, Any] = {
        "processed_at": processed_at,
        "persist_entity_id": persist_entity_id,
        "thumbnail_asset_path": thumbnail_asset_path or None,
        "face_detail_asset_path": face_detail_asset_path or None,
        "face_detail_count": payload.get("face_detail_count") or 0,
        "has_face_detail": bool(payload.get("face_detail_count") or face_detail_asset_path),
        "representative_asset_path": representative_asset_path or None,
        "representative_angle": representative_angle,
        "provider": stored_provider,
        "model": stored_model,
        "purpose": payload.get("purpose"),
        "angles": normalized_angles,
        "image_count": len(image_urls),
        "image_request": image_request,
        "image_generation": {
            "provider": stored_provider,
            "model": stored_model,
            "purpose": payload.get("purpose"),
            "prompt": payload.get("prompt"),
            "negative_prompt": payload.get("negative_prompt"),
            "multi_angle": payload.get("multi_angle"),
            "angles": normalized_angles,
            "images": images,
            "image_urls": image_urls,
            "images_by_angle": payload.get("images_by_angle") or {},
            "face_detail_images": payload.get("face_detail_images") or [],
            "face_detail_asset_path": face_detail_asset_path or None,
            "face_detail_count": payload.get("face_detail_count") or 0,
            "thumbnail_image": payload.get("thumbnail_image"),
            "thumbnail_asset_path": thumbnail_asset_path or None,
            "review": review,
            "review_status": review_status,
            "has_face_detail": bool(payload.get("face_detail_count") or face_detail_asset_path),
            "representative_asset_path": representative_asset_path or None,
            "representative_angle": representative_angle,
            "image_count": len(image_urls),
            "ref_image_uris": payload.get("ref_image_uris") or [],
        },
        "review_status": review_status,
    }
    stamp_lock_url(result_metadata, payload)
    result_metadata["effective_status"] = effective_task_status("ready", result_metadata)
    return result_url, result_metadata, image_urls
