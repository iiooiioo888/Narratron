"""把第三方生圖結果寫回角色護照（資產路徑 + `_extensions.image_gen`）。"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

from characteros.imaging.base import ImageGenRequest, ImageGenResult
from characteros.imaging.prompt import assemble_request
from characteros.imaging.ref_uris import WAN_MAX_REF_IMAGES, cap_ref_uris_for_api, normalize_ref_uris_for_api
from characteros.imaging.registry import get_provider
from narratron.charpass.image_gen_compact import compact_image_gen_extensions
from narratron.charpass.schema import manifest_to_dict
from narratron.charpass.style_prompt import (
    IDENTITY_SUPPLEMENTAL_ANGLES,
    MULTI_VIEW_ANGLES,
    PURPOSE_SLOTS,
    TPOSE_ANGLES,
    apply_default_character_style,
    default_single_angle_for_purpose,
)
from narratron.charpass.store import CharpassStore

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


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return {"type": "bytes", "size": len(value)}
    return str(value)


def _normalize_entity_id(value: Any, fallback_name: str) -> str:
    raw = str(value or "").strip()
    if raw:
        return raw
    name = str(fallback_name or "character").strip() or "character"
    return f"character-{name}"


def _asset_path_for_image(asset_dir: str, filename: str, angle: Any = None) -> str:
    clean_dir = str(asset_dir or "").strip().strip("/")
    clean_name = str(filename or "").strip().lstrip("/")
    return f"{clean_dir}/{clean_name}"


def _staging_asset_path(*, purpose: str, job_id: str, filename: str) -> str:
    clean_purpose = str(purpose or "identity").strip() or "identity"
    clean_name = str(filename or "").strip().lstrip("/")
    return f"causal/review/{clean_purpose}/{job_id}/{clean_name}"


def is_published_asset_relpath(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lstrip("/")
    return normalized == "assets" or normalized.startswith("assets/")


def _preview_asset_paths(payload: dict[str, Any]) -> list[str]:
    """收集可供預覽的路徑；不含 review.manifest_candidate 內的預定正式路徑。"""
    paths: list[str] = []

    def _push(value: Any) -> None:
        text = str(value or "").strip()
        if text:
            paths.append(text)

    for key in ("thumbnail_asset_path", "face_detail_asset_path", "representative_asset_path"):
        _push(payload.get(key))

    def _collect_image(item: Any) -> None:
        if not isinstance(item, dict):
            return
        _push(item.get("asset_path"))
        _push(item.get("path"))

    images = payload.get("images")
    if isinstance(images, list):
        for item in images:
            _collect_image(item)

    images_by_angle = payload.get("images_by_angle")
    if isinstance(images_by_angle, dict):
        for entries in images_by_angle.values():
            if isinstance(entries, list):
                for item in entries:
                    _collect_image(item)

    face_detail_images = payload.get("face_detail_images")
    if isinstance(face_detail_images, list):
        for item in face_detail_images:
            _collect_image(item)

    _collect_image(payload.get("thumbnail_image"))
    return paths


def ensure_unaccepted_generation_is_staged(payload: dict[str, Any]) -> None:
    """未接受的生圖結果，預覽路徑不得指向正式 `assets/`。"""
    review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    status = str(review.get("status") or payload.get("review_status") or "").strip().lower()
    if status in {"", "accepted"}:
        return
    for asset_path in _preview_asset_paths(payload):
        if is_published_asset_relpath(asset_path):
            raise RuntimeError("pending/rejected generation must not publish assets/")


def _asset_dir_for_generated_image(request: ImageGenRequest, image: Any) -> str:
    slot = PURPOSE_SLOTS.get(request.purpose, PURPOSE_SLOTS["identity"])
    override = ""
    metadata = getattr(image, "metadata", None)
    if isinstance(metadata, dict):
        override = str(metadata.get("asset_dir") or "").strip()
    return override or str(request.extra.get("asset_dir") or slot["asset_dir"])


def _resolved_image_angle(request: ImageGenRequest, image: Any) -> str | None:
    metadata = getattr(image, "metadata", None)
    if isinstance(metadata, dict):
        angle = str(metadata.get("angle") or "").strip()
        if angle:
            return angle
    request_angle = str(request.extra.get("angle") or "").strip()
    if request_angle:
        return request_angle
    fallback = default_single_angle_for_purpose(request.purpose)
    return fallback or None


def _default_angle_for_generation(*, purpose: str, requested_angle: Any = None) -> str | None:
    explicit = str(requested_angle or "").strip()
    if explicit:
        return explicit
    if purpose == "face_detail":
        return "face_detail"
    if purpose == "tpose":
        return "tpose"
    if purpose == "identity":
        return "front"
    return None


def _normalize_angle(value: Any) -> str:
    raw = str(value or "").strip()
    if raw:
        return raw
    return ""


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


def _image_angle_value(image: dict[str, Any]) -> str:
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


def _group_images_by_angle(images: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in images:
        normalized = dict(item)
        angle = _image_angle_value(normalized) or "unclassified"
        normalized["angle"] = angle
        grouped.setdefault(angle, []).append(normalized)
    ordered: dict[str, list[dict[str, Any]]] = {}
    for angle in sorted(grouped.keys(), key=lambda value: (ANGLE_SORT_ORDER.get(value, 999), value)):
        ordered[angle] = sorted(
            grouped[angle],
            key=lambda image: (
                0 if str(image.get("angle") or "") == "face_detail" else 1,
                str(image.get("filename") or ""),
                str(image.get("asset_path") or ""),
            ),
        )
    return ordered
 
 
def _ordered_asset_paths(images: list[dict[str, Any]]) -> list[str]:
    ordered = sorted(
        [item for item in images if isinstance(item, dict)],
        key=lambda image: (
            ANGLE_SORT_ORDER.get(_image_angle_value(image), 999),
            str(image.get("filename") or ""),
            str(image.get("asset_path") or ""),
        ),
    )
    return [
        str(item.get("asset_path") or "").strip()
        for item in ordered
        if str(item.get("asset_path") or "").strip()
    ]


def _face_detail_summary(images: list[dict[str, Any]]) -> dict[str, Any]:
    face_detail_images = [
        {**dict(item), "angle": _image_angle_value(item) or "face_detail"}
        for item in images
        if isinstance(item, dict) and _image_angle_value(item) == "face_detail"
    ]
    return {
        "face_detail_asset_path": (
            str(face_detail_images[0].get("asset_path") or "").strip() if face_detail_images else None
        ),
        "face_detail_count": len(face_detail_images),
        "face_detail_images": face_detail_images,
    }


def _thumbnail_candidate(refs: list[dict[str, Any]]) -> str:
    preferred_order = ("face_detail", "tpose", "front", "three_quarter", "left", "right", "back", "top", "bottom")
    for angle in preferred_order:
        for item in refs:
            if item.get("angle") == angle and item.get("path"):
                return str(item["path"])
    return str(refs[0].get("path") or "") if refs else ""


def _thumbnail_image_payload(images: list[dict[str, Any]]) -> dict[str, Any] | None:
    preferred_order = ("face_detail", "tpose", "front", "three_quarter", "left", "right", "back", "top", "bottom")
    for angle in preferred_order:
        for item in images:
            if item.get("angle") == angle:
                return dict(item)
    return dict(images[0]) if images else None


def _image_payload_summary(images: list[dict[str, Any]]) -> dict[str, Any]:
    grouped = _group_images_by_angle(images)
    thumbnail_image = _thumbnail_image_payload(images)
    face_detail_summary = _face_detail_summary(images)
    thumbnail_asset_path = ""
    if isinstance(thumbnail_image, dict):
        thumbnail_asset_path = str(thumbnail_image.get("asset_path") or "").strip()
    return {
        "images_by_angle": grouped,
        **face_detail_summary,
        "thumbnail_image": thumbnail_image,
        "thumbnail_asset_path": thumbnail_asset_path or face_detail_summary.get("face_detail_asset_path"),
    }


def _review_file_paths(payload: dict[str, Any]) -> dict[str, str]:
    review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    return {
        "full_response_path": str(review.get("full_response_path") or "").strip(),
        "images_index_path": str(review.get("images_index_path") or "").strip(),
        "record_path": str(review.get("record_path") or "").strip(),
    }


def _normalized_review_status(payload: dict[str, Any]) -> str | None:
    review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    status = str(review.get("status") or payload.get("review_status") or "").strip().lower()
    if status in {"pending", "accepted", "rejected"}:
        return status
    return None


def _artifact_status_for(payload: dict[str, Any]) -> str:
    review_status = _normalized_review_status(payload)
    if review_status == "accepted":
        return "accepted"
    if review_status == "rejected":
        return "rejected"
    if review_status == "pending":
        return "pending"
    return "ready"


def sync_review_artifacts(
    entity_id: str,
    payload: dict[str, Any],
    *,
    store: CharpassStore | None = None,
) -> None:
    """同步更新審核用回應檔，避免 queue metadata 與磁碟摘要不一致。"""

    active_store = store or CharpassStore()
    safe_payload = _json_safe(payload)
    paths = _review_file_paths(safe_payload)
    full_response_path = paths["full_response_path"]
    images_index_path = paths["images_index_path"]
    record_path = paths["record_path"]
    review = safe_payload.get("review") if isinstance(safe_payload.get("review"), dict) else {}
    review_status = _normalized_review_status(safe_payload)
    artifact_status = _artifact_status_for(safe_payload)
    if full_response_path:
        active_store.write_json(entity_id, full_response_path, safe_payload)
    if images_index_path:
        active_store.write_json(
            entity_id,
            images_index_path,
            {
                "job_id": (safe_payload.get("review") or {}).get("job_id"),
                "purpose": safe_payload.get("purpose"),
                "provider": safe_payload.get("provider"),
                "model": safe_payload.get("model"),
                "entity_id": entity_id,
                "thumbnail_asset_path": safe_payload.get("thumbnail_asset_path"),
                "face_detail_asset_path": safe_payload.get("face_detail_asset_path"),
                "face_detail_count": safe_payload.get("face_detail_count") or 0,
                "images": safe_payload.get("images") or [],
                "images_by_angle": safe_payload.get("images_by_angle") or {},
                "review": safe_payload.get("review") or {},
                "status": artifact_status,
                "review_status": review_status,
            },
        )
    if record_path:
        existing_record = active_store.read_json(entity_id, record_path)
        if not isinstance(existing_record, dict):
            existing_record = {}
        existing_record.update(
            {
                "job_id": review.get("job_id"),
                "purpose": safe_payload.get("purpose"),
                "provider": safe_payload.get("provider"),
                "model": safe_payload.get("model"),
                "status": artifact_status,
                "review_status": review_status,
                "accepted_at": review.get("accepted_at"),
                "rejected_at": review.get("rejected_at"),
                "thumbnail_asset_path": safe_payload.get("thumbnail_asset_path"),
                "face_detail_asset_path": safe_payload.get("face_detail_asset_path"),
                "face_detail_count": safe_payload.get("face_detail_count") or 0,
                "asset_paths": _ordered_asset_paths(safe_payload.get("images") or []),
                "angles": list((safe_payload.get("images_by_angle") or {}).keys()),
            }
        )
        active_store.write_json(entity_id, record_path, existing_record)


def _entity_file_path(store: CharpassStore, entity_id: str, relative_path: str) -> Path:
    rel = Path(str(relative_path or "").replace("\\", "/"))
    parts = [part for part in rel.parts if part not in {"", ".", ".."}]
    if not parts:
        raise ValueError("relative_path must not be empty")
    return store.entity_dir(entity_id).joinpath(*parts)


def finalize_reviewed_generation(
    entity_id: str,
    review_payload: dict[str, Any],
    *,
    store: CharpassStore | None = None,
) -> dict[str, Any]:
    """把待審核的圖片結果提升為正式資產，並回傳可寫入的 manifest。"""

    active_store = store or CharpassStore()
    payload = _json_safe(review_payload)
    review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    manifest = payload.get("manifest_candidate")
    if not isinstance(manifest, dict):
        manifest = review.get("manifest_candidate")
    if not isinstance(manifest, dict):
        raise ValueError("review payload missing manifest_candidate")

    images = payload.get("images")
    if not isinstance(images, list):
        images = []
        payload["images"] = images

    for image in images:
        if not isinstance(image, dict):
            continue
        src_rel = str(image.get("asset_path") or "").strip()
        dst_rel = str(image.get("final_asset_path") or src_rel).strip()
        if not src_rel or not dst_rel:
            continue
        src = _entity_file_path(active_store, entity_id, src_rel)
        dst = _entity_file_path(active_store, entity_id, dst_rel)
        if src.is_file() and src != dst:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
        image["asset_path"] = dst_rel

    review["status"] = "accepted"
    review["accepted_at"] = _utcnow()
    review.pop("rejected_at", None)
    payload.update(_image_payload_summary(images))
    payload["review"] = review
    payload["review_status"] = "accepted"
    sync_review_artifacts(entity_id, payload, store=active_store)
    return {"manifest": manifest, "payload": payload}


def _generation_angles_for(purpose: str, multi_angle: bool) -> list[dict[str, str]]:
    if not multi_angle:
        return []
    if purpose == "face_detail":
        return list(IDENTITY_SUPPLEMENTAL_ANGLES)
    if purpose == "tpose":
        return list(TPOSE_ANGLES)
    angles = list(MULTI_VIEW_ANGLES)
    if purpose == "identity":
        angles.extend(IDENTITY_SUPPLEMENTAL_ANGLES)
    return angles


def apply_result_to_manifest(
    manifest: dict[str, Any],
    request: ImageGenRequest,
    result: ImageGenResult,
    *,
    job_id: str | None = None,
) -> dict[str, Any]:
    """把產出圖的路徑／URL 寫入對應層；核心仍不呼叫 generate。"""

    data = manifest_to_dict(manifest)
    slot = PURPOSE_SLOTS.get(request.purpose, PURPOSE_SLOTS["identity"])
    current_job_id = str(job_id or uuid4())
    refs: list[dict[str, Any]] = []
    for image in result.images:
        angle = _resolved_image_angle(request, image) or _infer_angle_from_text(image.filename, image.url)
        path = _asset_path_for_image(_asset_dir_for_generated_image(request, image), image.filename, angle)
        note = f"generated:{result.provider}:{request.purpose}"
        if angle:
            note = f"{note}:{angle}"
        ref_item = {
            "path": path,
            "uri": image.url or path,
            "kind": "reference_image",
            "angle": angle,
            "note": note,
        }
        age_value = request.extra.get("age") if isinstance(request.extra, dict) else None
        if age_value not in (None, ""):
            ref_item["age"] = age_value
        refs.append(ref_item)

    style = data.setdefault("_style", {})
    identity = data.setdefault("_identity", {})
    generated_keys = {
        (ref.get("angle"), ref.get("age"))
        for ref in refs
        if ref.get("angle")
    }

    def _replace_angles(existing: list[dict[str, Any]] | list[Any]) -> list[Any]:
        # 針對同一個角度（front/back/...）做覆蓋，避免重複累積舊版本。
        filtered: list[Any] = []
        for item in existing:
            if not isinstance(item, dict):
                filtered.append(item)
                continue
            key = (item.get("angle"), item.get("age"))
            if key in generated_keys or (
                item.get("age") in (None, "") and item.get("angle") in {angle for angle, _age in generated_keys}
            ):
                continue
            filtered.append(item)
        return filtered

    pipeline = str(request.extra.get("pipeline") or "").strip() if isinstance(request.extra, dict) else ""
    if pipeline == "age_span":
        # 年齡軸只寫入 _extensions.image_gen.age_span，不污染 identity.ref_images。
        pass
    elif request.purpose in {"identity", "face_detail", "tpose"}:
        existing = identity.setdefault("ref_images", [])
        identity["ref_images"] = _replace_angles(existing)
        identity["ref_images"].extend(refs)
    elif request.purpose == "outfit":
        outfit = style.setdefault("outfit", {})
        existing = outfit.setdefault("ref_images", [])
        outfit["ref_images"] = _replace_angles(existing)
        outfit["ref_images"].extend(refs)
    else:
        existing = style.setdefault("reference_images", [])
        style["reference_images"] = _replace_angles(existing)
        style["reference_images"].extend(refs)

    extensions = data.setdefault("_extensions", {})
    image_gen = extensions.setdefault("image_gen", {})
    image_gen["provider"] = result.provider
    image_gen["model"] = result.model
    image_gen["last_job_id"] = current_job_id
    image_gen["last_asset_paths"] = _ordered_asset_paths(
        [{"angle": item.get("angle"), "asset_path": item.get("path"), "filename": item.get("path")} for item in refs]
    )
    image_gen["size"] = request.size
    image_gen["last_purpose"] = request.purpose
    image_gen["last_angles"] = [
        angle for angle in _group_images_by_angle(
            [{"angle": item.get("angle"), "asset_path": item.get("path"), "filename": item.get("path")} for item in refs]
        ).keys()
    ]
    face_detail_paths = [item["path"] for item in refs if item.get("angle") == "face_detail" and item.get("path")]
    if face_detail_paths:
        image_gen["last_face_detail_paths"] = face_detail_paths
    if pipeline == "age_span":
        age_span = image_gen.setdefault("age_span", {"faces": {}, "tposes": {}})
        if not isinstance(age_span, dict):
            age_span = {"faces": {}, "tposes": {}}
            image_gen["age_span"] = age_span
        bucket = "faces" if request.purpose == "face_detail" else "tposes" if request.purpose == "tpose" else "other"
        bucket_data = age_span.setdefault(bucket, {})
        if isinstance(bucket_data, dict):
            age_key = str((request.extra or {}).get("age") or "")
            if age_key:
                bucket_data[age_key] = refs
    latest_by_purpose = image_gen.setdefault("latest_by_purpose", {})
    if isinstance(latest_by_purpose, dict):
        summary_images = [
            {"angle": item.get("angle"), "asset_path": item.get("path"), "filename": item.get("path")}
            for item in refs
        ]
        grouped_images = _group_images_by_angle(summary_images)
        ordered_asset_paths = _ordered_asset_paths(summary_images)
        face_detail_summary = _face_detail_summary(summary_images)
        latest_by_purpose[request.purpose] = {
            "job_id": current_job_id,
            "provider": result.provider,
            "model": result.model,
            "asset_paths": ordered_asset_paths,
            "angles": list(grouped_images.keys()),
            "images_by_angle": grouped_images,
            "thumbnail_asset_path": _thumbnail_candidate(refs) or None,
            **face_detail_summary,
            "updated_at": _utcnow(),
        }
    meta = data.setdefault("_meta", {})
    thumb_path = _thumbnail_candidate(refs)
    if request.purpose == "thumb":
        meta["thumbnail"] = thumb_path or meta.get("thumbnail") or ""
    elif request.purpose in {"identity", "face_detail"} and thumb_path:
        meta["thumbnail"] = thumb_path
    meta["updated_at"] = _utcnow()
    return compact_image_gen_extensions(data)


class ImagingService:
    """CharacterOS 生圖編排：組 prompt → provider.generate → 可選寫回本機護照。"""

    def __init__(self, store: CharpassStore | None = None) -> None:
        self.store = store or CharpassStore()

    def _prepare_request_for_provider(
        self,
        request: ImageGenRequest,
        *,
        entity_id: str,
        provider_name: str | None = None,
        manifest: dict | None = None,
    ) -> ImageGenRequest:
        preferred_angle = None
        if isinstance(request.extra, dict):
            preferred_angle = str(request.extra.get("angle") or "").strip() or None
        provider = str(provider_name or "wan").strip().lower()
        if provider == "wan":
            normalized = [
                str(uri).strip()
                for uri in request.ref_image_uris
                if str(uri or "").strip().lower().startswith(("http://", "https://"))
            ]
        else:
            normalized = normalize_ref_uris_for_api(
                list(request.ref_image_uris),
                store=self.store,
                entity_id=entity_id,
            )
        prepared = cap_ref_uris_for_api(
            normalized,
            provider=provider_name or "wan",
            manifest=manifest,
            preferred_angle=preferred_angle,
        )
        if prepared == request.ref_image_uris:
            return request
        return request.model_copy(update={"ref_image_uris": prepared})

    def _download_remote_assets(self, result: ImageGenResult) -> dict[str, bytes]:
        """下載 provider 回傳但未直接附帶 bytes 的遠端圖片。"""
        pending = [image for image in result.images if image.url and image.data is None]
        if not pending:
            return {}
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("保存遠端生圖結果需要 httpx：pip install httpx") from exc

        downloaded: dict[str, bytes] = {}
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            for image in pending:
                url = str(image.url or "").strip()
                if not url.startswith(("http://", "https://")):
                    logger.warning("Skip non-http image URL for persist: %s", url)
                    continue
                response = client.get(url)
                response.raise_for_status()
                image.data = response.content
                downloaded[image.filename] = response.content
        return downloaded

    def _build_generation_record(
        self,
        request: ImageGenRequest,
        result: ImageGenResult,
        payload: dict[str, Any],
        *,
        job_id: str,
    ) -> dict[str, Any]:
        """整理單次生成紀錄，供落盤與回寫 manifest。"""
        return {
            "job_id": job_id,
            "created_at": _utcnow(),
            "provider": result.provider,
            "model": result.model,
            "purpose": request.purpose,
            "size": request.size,
            "multi_angle": bool(payload.get("multi_angle")),
            "angles": list(payload.get("angles") or []),
            "request": {
                "purpose": request.purpose,
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt,
                "size": request.size,
                "n": request.n,
                "model": request.model,
                "ref_image_uris": list(request.ref_image_uris),
                "extra": _json_safe(request.extra),
            },
            "response": {
                "provider": result.provider,
                "model": result.model,
                "images": _json_safe(payload.get("images") or []),
                "images_by_angle": _group_images_by_angle(_json_safe(payload.get("images") or [])),
                "raw": _json_safe(result.raw),
            },
        }

    def generate_for_manifest(
        self,
        manifest: dict[str, Any],
        *,
        purpose: str = "identity",
        provider_name: str | None = None,
        extra: str = "",
        n: int = 1,
        model: str = "",
        base_url: str = "",
        api_key: str = "",
        persist_entity_id: str | None = None,
        multi_angle: bool = True,
        auto_accept: bool = True,
        extra_ref_uris: list[str] | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        manifest = apply_default_character_style(manifest)
        provider = get_provider(
            provider_name,
            model=(model or None),
            base_url=(base_url or None),
            api_key=(api_key or None),
        )
        entity_name = (
            manifest.get("_identity", {}).get("name")
            or manifest.get("_meta", {}).get("character_name")
            or "character"
        )
        entity_id = _normalize_entity_id(
            persist_entity_id
            or manifest.get("_meta", {}).get("entity_id")
            or manifest.get("_identity", {}).get("entity_id"),
            entity_name,
        )

        if multi_angle:
            all_images = []
            prompt_lines: list[str] = []
            negative_prompt = ""
            last_request: ImageGenRequest | None = None
            last_result: ImageGenResult | None = None
            angle_defs = _generation_angles_for(purpose, multi_angle)

            for angle_def in angle_defs:
                request = self._prepare_request_for_provider(
                    assemble_request(
                        manifest,
                        purpose=purpose,
                        extra=extra,
                        n=1,
                        model=model,
                        angle=angle_def["key"],
                        multi_angle=True,
                        extra_ref_uris=extra_ref_uris,
                        extra_fields=extra_fields,
                    ),
                    entity_id=entity_id,
                    provider_name=provider.name,
                    manifest=manifest,
                )
                result = provider.generate(request)
                for image in result.images:
                    image.metadata.setdefault("angle", angle_def["key"])
                    if angle_def["key"] == "face_detail":
                        image.metadata.setdefault("asset_dir", PURPOSE_SLOTS["face_detail"]["asset_dir"])
                all_images.extend(result.images)
                prompt_lines.append(f"[{angle_def['key']}] {request.prompt}")
                negative_prompt = request.negative_prompt
                last_request = request
                last_result = result

            if not last_request or not last_result:
                raise RuntimeError("多視角生圖未產出任何結果")

            combined = ImageGenResult(
                provider=last_result.provider,
                model=last_result.model,
                images=all_images,
                raw={"multi_angle": True, "angles": [item["key"] for item in angle_defs]},
            )
            request = last_request
            result = combined
            combined_prompt = "\n".join(prompt_lines)
        else:
            request = self._prepare_request_for_provider(
                assemble_request(
                    manifest,
                    purpose=purpose,
                    extra=extra,
                    n=n,
                    model=model,
                    multi_angle=False,
                    extra_ref_uris=extra_ref_uris,
                    extra_fields=extra_fields,
                ),
                entity_id=entity_id,
                provider_name=provider.name,
                manifest=manifest,
            )
            result = provider.generate(request)
            default_angle = _default_angle_for_generation(
                purpose=purpose,
                requested_angle=request.extra.get("angle") if isinstance(request.extra, dict) else None,
            )
            for image in result.images:
                if default_angle:
                    image.metadata.setdefault("angle", default_angle)
                if default_angle == "face_detail":
                    image.metadata.setdefault("asset_dir", PURPOSE_SLOTS["face_detail"]["asset_dir"])
            combined_prompt = request.prompt

        job_id = str(uuid4())
        source_manifest = copy.deepcopy(manifest) if not auto_accept else manifest
        updated = apply_result_to_manifest(source_manifest, request, result, job_id=job_id)
        updated.setdefault("_meta", {})["entity_id"] = entity_id
        updated.setdefault("_identity", {})["entity_id"] = entity_id
        angles = [item["key"] for item in _generation_angles_for(purpose, multi_angle)] if multi_angle else []
        images_payload = [
            {
                "filename": image.filename,
                "url": image.url,
                "has_bytes": image.data is not None,
                "mime_type": image.mime_type,
                "angle": _resolved_image_angle(request, image) or _infer_angle_from_text(image.filename, image.url),
                "requested_angle": (
                    str(request.extra.get("angle") or "").strip() if isinstance(request.extra, dict) else ""
                ),
                "requested_purpose": purpose,
                "prompt": combined_prompt if multi_angle else request.prompt,
                "asset_path": _asset_path_for_image(
                    _asset_dir_for_generated_image(request, image),
                    image.filename,
                    _resolved_image_angle(request, image) or _infer_angle_from_text(image.filename, image.url),
                ),
            }
            for image in result.images
        ]
        payload = {
            "provider": result.provider,
            "model": result.model,
            "purpose": purpose,
            "prompt": combined_prompt,
            "negative_prompt": request.negative_prompt,
            "ref_image_uris": request.ref_image_uris,
            "multi_angle": multi_angle,
            "angles": angles,
            "images": images_payload,
            "manifest": updated,
        }
        payload.update(_image_payload_summary(images_payload))

        # 若要持久化，除了更新 ref_images，也要把「AI 回傳內容」保存下來，方便之後追溯／再次生成。
        if persist_entity_id:
            self._download_remote_assets(result)
            generation_record = self._build_generation_record(
                request,
                result,
                payload,
                job_id=job_id,
            )
            purpose_dir = f"causal/image_gen/{request.purpose}/{job_id}"
            final_images_payload: list[dict[str, Any]] = []
            for item in images_payload:
                actual = dict(item)
                final_asset_path = str(item.get("asset_path") or "").strip()
                if auto_accept:
                    actual["asset_path"] = final_asset_path
                else:
                    actual["asset_path"] = _staging_asset_path(
                        purpose=request.purpose,
                        job_id=job_id,
                        filename=str(item.get("filename") or ""),
                    )
                    actual["final_asset_path"] = final_asset_path
                final_images_payload.append(actual)
            payload["images"] = final_images_payload
            payload.update(_image_payload_summary(final_images_payload))
            payload["review"] = {
                "status": "accepted" if auto_accept else "pending",
                "auto_accept": auto_accept,
                "job_id": job_id,
                "entity_id": persist_entity_id,
                "purpose": request.purpose,
                "staged_at": None if auto_accept else _utcnow(),
                "manifest_candidate": None if auto_accept else compact_image_gen_extensions(copy.deepcopy(updated)),
                "request_path": f"{purpose_dir}/request.json",
                "response_path": f"{purpose_dir}/response.json",
                "full_response_path": f"{purpose_dir}/full-response.json",
                "raw_response_path": f"{purpose_dir}/raw-response.json",
                "record_path": f"{purpose_dir}/record.json",
                "images_index_path": f"{purpose_dir}/images-index.json",
            }
            payload["review_status"] = payload["review"]["status"]
            self.store.write_json(entity_id, f"{purpose_dir}/request.json", generation_record["request"])
            self.store.write_json(
                entity_id,
                f"{purpose_dir}/response.json",
                {
                    **generation_record["response"],
                    "images": _json_safe(final_images_payload),
                    "images_by_angle": _group_images_by_angle(_json_safe(final_images_payload)),
                },
            )
            self.store.write_json(entity_id, f"{purpose_dir}/full-response.json", _json_safe(payload))
            self.store.write_json(
                entity_id,
                f"{purpose_dir}/raw-response.json",
                _json_safe(result.raw),
            )
            self.store.write_json(entity_id, f"{purpose_dir}/record.json", generation_record)
            self.store.write_json(
                entity_id,
                f"{purpose_dir}/images-index.json",
                {
                    "job_id": job_id,
                    "purpose": request.purpose,
                    "provider": result.provider,
                    "model": result.model,
                    "entity_id": entity_id,
                    "asset_dir": str(request.extra.get("asset_dir") or PURPOSE_SLOTS.get(request.purpose, PURPOSE_SLOTS["identity"])["asset_dir"]),
                    "thumbnail_image": payload.get("thumbnail_image"),
                    "thumbnail_asset_path": payload.get("thumbnail_asset_path"),
                    "face_detail_images": payload.get("face_detail_images") or [],
                    "face_detail_asset_path": payload.get("face_detail_asset_path"),
                    "face_detail_count": payload.get("face_detail_count") or 0,
                    "images": final_images_payload,
                    "images_by_angle": _group_images_by_angle(final_images_payload),
                    "review": payload.get("review") or {},
                    "review_status": payload.get("review_status"),
                },
            )
            assets = {
                (
                    _asset_path_for_image(
                        _asset_dir_for_generated_image(request, image),
                        image.filename,
                        _resolved_image_angle(request, image),
                    )
                    if auto_accept
                    else _staging_asset_path(
                        purpose=request.purpose,
                        job_id=job_id,
                        filename=image.filename,
                    )
                ): image.data
                for image in result.images
                if image.data
            }
            if assets:
                if not auto_accept:
                    leaked = [path for path in assets if is_published_asset_relpath(path)]
                    if leaked:
                        raise RuntimeError("pending review must not write formal assets/")
                self.store.write_assets(entity_id, assets)
            if auto_accept:
                extensions = updated.setdefault("_extensions", {})
                image_gen = extensions.setdefault("image_gen", {})
                image_gen["last_api_response_path"] = f"{purpose_dir}/full-response.json"
                image_gen["last_request_path"] = f"{purpose_dir}/request.json"
                image_gen["last_raw_response_path"] = f"{purpose_dir}/raw-response.json"
                image_gen["last_record_path"] = f"{purpose_dir}/record.json"
                image_gen["last_images_index_path"] = f"{purpose_dir}/images-index.json"

                history = image_gen.setdefault("history", [])
                if not isinstance(history, list):
                    history = []
                    image_gen["history"] = history
                history.append(
                    {
                        "job_id": job_id,
                        "purpose": request.purpose,
                        "provider": result.provider,
                        "model": result.model,
                        "created_at": _utcnow(),
                        "request_path": image_gen["last_request_path"],
                        "response_path": image_gen["last_api_response_path"],
                        "raw_response_path": image_gen["last_raw_response_path"],
                        "record_path": image_gen["last_record_path"],
                        "images_index_path": image_gen["last_images_index_path"],
                        "asset_paths": list(image_gen.get("last_asset_paths") or []),
                        "angles": list(image_gen.get("last_angles") or []),
                    }
                )
                image_gen["history"] = history[-20:]
                compact_image_gen_extensions(updated)
                try:
                    self.store.write_manifest(entity_id, updated, snapshot_history=False)
                except OSError as exc:
                    logger.warning("生圖資產已寫入，略過護照寫入（檔案被占用）：%s", exc)

        if not auto_accept:
            ensure_unaccepted_generation_is_staged(payload)
        return payload
