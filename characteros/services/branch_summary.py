"""共用版本分支摘要與排序邏輯（local / database 雙後端）。"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

ANGLE_SORT_ORDER = {
    "face_detail": 0,
    "tpose": 1,
    "front": 2,
    "three_quarter": 3,
    "left": 4,
    "right": 5,
    "back": 6,
    "top": 7,
    "bottom": 8,
}

ANGLE_HINTS = {
    "face_detail": ("face_detail", "face-detail", "face detail"),
    "tpose": ("tpose", "t-pose", "t pose", "t型"),
}

KNOWN_ANGLES = tuple(ANGLE_SORT_ORDER.keys())


def first_ref_path(refs: Any, *preferred_angles: str) -> str | None:
    if not isinstance(refs, list):
        return None
    items = [item for item in refs if isinstance(item, dict)]
    for angle in preferred_angles:
        for item in items:
            if str(item.get("angle") or "").strip() == angle and str(item.get("path") or "").strip():
                return str(item.get("path")).strip()
    for item in items:
        path = str(item.get("path") or "").strip()
        if path:
            return path
    return None


def _normalize_angle(value: Any) -> str:
    raw = str(value or "").strip()
    return raw if raw else ""


def _infer_angle_from_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip().lower()
        if not text:
            continue
        for angle, hints in ANGLE_HINTS.items():
            if any(hint in text for hint in hints):
                return angle
        for angle in KNOWN_ANGLES:
            normalized = angle.replace("_", " ")
            if f"[{angle}]" in text or angle in text or normalized in text:
                return angle
    return ""


def _infer_angle_from_prompt(prompt: Any) -> str:
    text = str(prompt or "").strip().lower()
    if not text:
        return ""
    for angle in KNOWN_ANGLES:
        if f"[{angle}]" in text:
            return angle
    return ""


def image_angle_value(image: dict[str, Any]) -> str:
    if not isinstance(image, dict):
        return ""
    explicit = _normalize_angle(image.get("angle"))
    if explicit:
        return explicit
    requested_angle = _normalize_angle(image.get("requested_angle"))
    if requested_angle:
        return requested_angle
    prompt_angle = _infer_angle_from_prompt(image.get("prompt"))
    if prompt_angle:
        return prompt_angle
    purpose = str(image.get("purpose") or image.get("requested_purpose") or "").strip()
    if purpose == "face_detail":
        return "face_detail"
    if purpose == "tpose":
        return "tpose"
    return _infer_angle_from_text(
        image.get("final_asset_path"),
        image.get("asset_path"),
        image.get("filename"),
        image.get("note"),
        image.get("prompt"),
        image.get("uri"),
        image.get("url"),
    )


def summary_images_from_payload(
    image_generation: dict[str, Any],
    result_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    images = image_generation.get("images")
    if isinstance(images, list) and images:
        return images

    flattened: list[dict[str, Any]] = []
    images_by_angle = image_generation.get("images_by_angle")
    if isinstance(images_by_angle, dict):
        for angle, entries in images_by_angle.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                normalized = dict(entry)
                normalized.setdefault("angle", str(angle))
                normalized.setdefault(
                    "filename",
                    normalized.get("asset_path") or normalized.get("final_asset_path") or str(angle),
                )
                flattened.append(normalized)
    if flattened:
        return flattened

    fallback_images: list[dict[str, Any]] = []
    for source in (
        image_generation.get("face_detail_images"),
        [image_generation.get("thumbnail_image")],
    ):
        if not isinstance(source, list):
            continue
        for entry in source:
            if not isinstance(entry, dict):
                continue
            normalized = dict(entry)
            normalized.setdefault("angle", image_angle_value(normalized) or "unclassified")
            normalized.setdefault(
                "filename",
                normalized.get("asset_path") or normalized.get("final_asset_path") or normalized.get("angle") or "image",
            )
            fallback_images.append(normalized)

    for angle, asset_path in (
        ("face_detail", result_metadata.get("face_detail_asset_path")),
        ("front", result_metadata.get("thumbnail_asset_path")),
    ):
        path = str(asset_path or "").strip()
        if not path:
            continue
        fallback_images.append(
            {
                "angle": angle,
                "asset_path": path,
                "filename": path,
            }
        )
    return fallback_images


def sort_images(images: Any) -> list[dict[str, Any]]:
    if not isinstance(images, list):
        return []
    items = [dict(item) for item in images if isinstance(item, dict)]
    for item in items:
        normalized_angle = image_angle_value(item)
        if normalized_angle:
            item["angle"] = normalized_angle
    items.sort(
        key=lambda item: (
            ANGLE_SORT_ORDER.get(image_angle_value(item), 999),
            str(item.get("filename") or item.get("final_asset_path") or ""),
            str(item.get("asset_path") or item.get("final_asset_path") or ""),
        )
    )
    return items


def images_by_angle_summary(images: Any) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in sort_images(images):
        angle = image_angle_value(item) or "unclassified"
        item["angle"] = angle
        grouped.setdefault(angle, []).append(item)
    return grouped


def branch_summary(
    images: Any,
    *,
    kind: str = "image_gen",
    branch_id: str = "",
    purpose: str | None = None,
    status: str | None = None,
    review_status: str | None = None,
    updated_at: Any = None,
) -> dict[str, Any]:
    ordered_images = sort_images(images)
    asset_paths = [
        str(item.get("asset_path") or "").strip()
        for item in ordered_images
        if str(item.get("asset_path") or "").strip()
    ]
    grouped = images_by_angle_summary(ordered_images)
    thumbnail_asset_path = first_ref_path(
        [{"angle": item.get("angle"), "path": item.get("asset_path")} for item in ordered_images],
        "face_detail",
        "front",
        "three_quarter",
        "left",
        "right",
        "back",
        "top",
        "bottom",
    )
    face_detail_images = grouped.get("face_detail") or []
    normalized_review_status = str(review_status or "").strip() or None
    normalized_status = str(status or "").strip() or "ready"
    effective_status = normalized_review_status or normalized_status
    angles = list(grouped.keys())
    purpose_summary = str(purpose or kind or "branch").strip()
    angles_summary = ", ".join(angles)
    has_face_detail = bool(face_detail_images)
    image_count = len(asset_paths)
    # `branches` 會以 reverse=True 排序，因此數值越大代表越前面。
    sort_priority = 2 if str(purpose or "").strip() == "face_detail" else 1 if has_face_detail else 0
    status_summary = effective_status or normalized_status
    face_detail_summary = f"face_detail x{len(face_detail_images)}" if face_detail_images else ""
    hero_asset_path = (
        str(face_detail_images[0].get("asset_path") or "").strip()
        if face_detail_images
        else thumbnail_asset_path
    )
    representative_angle = "face_detail" if face_detail_images else (angles[0] if angles else None)
    review_label = normalized_review_status or normalized_status
    return {
        "status": status_summary,
        "review_status": normalized_review_status,
        "effective_status": effective_status,
        "asset_paths": asset_paths,
        "angles": angles,
        "angles_summary": angles_summary,
        "images_by_angle": grouped,
        "thumbnail_asset_path": thumbnail_asset_path,
        "face_detail_asset_path": (
            str(face_detail_images[0].get("asset_path") or "").strip() if face_detail_images else None
        ),
        "has_face_detail": has_face_detail,
        "face_detail_count": len(face_detail_images),
        "face_detail_summary": face_detail_summary,
        "image_count": image_count,
        "purpose_summary": purpose_summary,
        "hero_asset_path": hero_asset_path or None,
        "representative_asset_path": hero_asset_path or None,
        "representative_angle": representative_angle,
        "review_label": review_label,
        "sort_priority": sort_priority,
        "summary_fields": {
            "status": status_summary,
            "review_status": normalized_review_status,
            "effective_status": effective_status,
            "purpose": purpose_summary,
            "angles": angles,
            "angles_summary": angles_summary,
            "image_count": image_count,
            "has_face_detail": has_face_detail,
            "face_detail_count": len(face_detail_images),
            "thumbnail_asset_path": thumbnail_asset_path,
            "face_detail_asset_path": (
                str(face_detail_images[0].get("asset_path") or "").strip() if face_detail_images else None
            ),
            "hero_asset_path": hero_asset_path or None,
            "representative_asset_path": hero_asset_path or None,
            "representative_angle": representative_angle,
            "review_label": review_label,
            "sort_priority": sort_priority,
        },
        "summary": " | ".join(
            part
            for part in (
                status_summary,
                purpose_summary,
                angles_summary,
                face_detail_summary,
                f"{image_count} images" if image_count else "",
            )
            if part
        ),
        "sort_key": f"{sort_priority}:{str(updated_at or '')}:{kind}:{branch_id}",
        "updated_at": updated_at,
    }


def review_rank(value: Any) -> int:
    normalized = str(value or "").strip().lower()
    if normalized == "pending":
        return 0
    if normalized == "ready":
        return 1
    if normalized == "accepted":
        return 2
    if normalized == "rejected":
        return 3
    if normalized == "failed":
        return 4
    return 5


def branch_visual_rank(branch: dict[str, Any]) -> int:
    purpose = str(branch.get("purpose") or branch.get("purpose_summary") or "").strip()
    if purpose == "face_detail":
        return 0
    angles = branch.get("angles") if isinstance(branch.get("angles"), list) else []
    if "face_detail" in [str(item).strip() for item in angles]:
        return 1
    if branch.get("representative_asset_path") or branch.get("thumbnail_asset_path"):
        return 2
    return 3


def _updated_sort_value(value: Any) -> float:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    if isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return 0.0
    return 0.0


def branch_sort_tuple(branch: dict[str, Any]) -> tuple[int, int, float, str, str]:
    return (
        branch_visual_rank(branch),
        review_rank(branch.get("effective_status") or branch.get("review_status") or branch.get("status")),
        -_updated_sort_value(branch.get("updated_at")),
        str(branch.get("kind") or ""),
        str(branch.get("branch_id") or ""),
    )


def _strip_final_asset_path_from_image_item(item: object) -> None:
    if isinstance(item, dict):
        item.pop("final_asset_path", None)


def strip_final_asset_path_from_image_generation(image_generation: dict) -> None:
    """
    pending/rejected 任務的 staging preview 只應該使用 `asset_path`，
    否則前端會優先抓 `final_asset_path` 造成檔案尚未落地而 404。
    """
    images = image_generation.get("images")
    if isinstance(images, list):
        for item in images:
            _strip_final_asset_path_from_image_item(item)

    images_by_angle = image_generation.get("images_by_angle")
    if isinstance(images_by_angle, dict):
        for entries in images_by_angle.values():
            if isinstance(entries, list):
                for item in entries:
                    _strip_final_asset_path_from_image_item(item)

    face_detail_images = image_generation.get("face_detail_images")
    if isinstance(face_detail_images, list):
        for item in face_detail_images:
            _strip_final_asset_path_from_image_item(item)

    thumbnail_image = image_generation.get("thumbnail_image")
    if thumbnail_image and isinstance(thumbnail_image, dict):
        _strip_final_asset_path_from_image_item(thumbnail_image)


# 與既有 service 內部命名對齊，避免重構後 import 路徑分裂。
_branch_summary = branch_summary
_branch_sort_tuple = branch_sort_tuple
_branch_visual_rank = branch_visual_rank
_review_rank = review_rank
_images_by_angle_summary = images_by_angle_summary
_sort_images = sort_images
_summary_images_from_payload = summary_images_from_payload
_strip_final_asset_path_from_image_generation = strip_final_asset_path_from_image_generation


def strip_final_asset_path_from_branch(branch: dict[str, Any]) -> None:
    """版本分支詳情：pending/rejected 剝除 images_by_angle 內的 final_asset_path。

    只改 API 回傳用的 branch dict，先 deepcopy 巢狀影像，避免碰到 job JSON 原物件。
    """
    review_status = str(
        branch.get("review_status") or branch.get("effective_status") or branch.get("status") or ""
    ).strip().lower()
    if review_status in {"", "accepted"}:
        return

    images_by_angle = branch.get("images_by_angle")
    if isinstance(images_by_angle, dict):
        branch["images_by_angle"] = copy.deepcopy(images_by_angle)
        for entries in branch["images_by_angle"].values():
            if isinstance(entries, list):
                for item in entries:
                    _strip_final_asset_path_from_image_item(item)

    response = branch.get("response")
    if isinstance(response, dict):
        branch["response"] = copy.deepcopy(response)
        nested = branch["response"].get("images_by_angle")
        if isinstance(nested, dict):
            for entries in nested.values():
                if isinstance(entries, list):
                    for item in entries:
                        _strip_final_asset_path_from_image_item(item)
        nested_images = branch["response"].get("images")
        if isinstance(nested_images, list):
            for item in nested_images:
                _strip_final_asset_path_from_image_item(item)
