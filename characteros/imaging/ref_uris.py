"""把 ref_image_uris 正規化並依 provider 上限裁剪，供第三方生圖 API 使用。"""

from __future__ import annotations

import base64
import io
import logging
import mimetypes
from pathlib import Path

from narratron.charpass.store import CharpassStore

logger = logging.getLogger(__name__)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_flatten_cache: dict[str, str | None] = {}


def is_api_ready_ref_uri(uri: str) -> bool:
    cleaned = str(uri or "").strip()
    if not cleaned:
        return False
    lowered = cleaned.lower()
    return lowered.startswith(("http://", "https://", "data:"))


def _guess_mime(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "image/png"


def _png_has_alpha(payload: bytes) -> bool:
    if len(payload) < 26 or payload[:8] != _PNG_SIGNATURE:
        return False
    color_type = payload[25]
    return color_type in {3, 4, 6}


def _flatten_image_bytes(payload: bytes) -> tuple[bytes, str] | None:
    """WAN 不接受透明 PNG；轉成不透明 JPEG。"""
    try:
        from PIL import Image
    except ImportError:
        if payload[:8] == _PNG_SIGNATURE and _png_has_alpha(payload):
            return None
        mime = "image/png" if payload[:8] == _PNG_SIGNATURE else "image/jpeg"
        return payload, mime

    try:
        image = Image.open(io.BytesIO(payload))
        if image.mode in {"RGBA", "LA", "P"}:
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            image = background
        else:
            image = image.convert("RGB")
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=90)
        return out.getvalue(), "image/jpeg"
    except Exception as exc:
        logger.warning("參考圖去透明失敗：%s", exc)
        return None


def _bytes_to_data_uri(payload: bytes, mime: str) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def flatten_ref_uri_for_wan(uri: str) -> str | None:
    cleaned = str(uri or "").strip()
    if not cleaned:
        return None
    if cleaned in _flatten_cache:
        return _flatten_cache[cleaned]
    payload: bytes | None = None
    if cleaned.lower().startswith("data:"):
        header, _, data = cleaned.partition(",")
        if ";base64" not in header.lower() or not data:
            _flatten_cache[cleaned] = cleaned
            return cleaned
        try:
            payload = base64.b64decode(data)
        except Exception:
            _flatten_cache[cleaned] = None
            return None
    elif cleaned.lower().startswith(("http://", "https://")):
        # 遠端 URL 直接交給 WAN，避免轉成巨大 data URI 觸發 400
        _flatten_cache[cleaned] = cleaned
        return cleaned
    if payload is None:
        _flatten_cache[cleaned] = cleaned
        return cleaned
    flattened = _flatten_image_bytes(payload)
    if flattened is None:
        result = None if _png_has_alpha(payload) else cleaned
        _flatten_cache[cleaned] = result
        return result
    body, mime = flattened
    result = _bytes_to_data_uri(body, mime)
    _flatten_cache[cleaned] = result
    return result


def flatten_ref_uris_for_wan(uris: list[str]) -> list[str]:
    prepared: list[str] = []
    seen: set[str] = set()
    for uri in uris:
        cleaned = str(uri or "").strip()
        if not cleaned.lower().startswith(("http://", "https://")):
            continue
        flattened = flatten_ref_uri_for_wan(cleaned)
        if not flattened or not flattened.lower().startswith(("http://", "https://")):
            continue
        if flattened in seen:
            continue
        seen.add(flattened)
        prepared.append(flattened)
        if len(prepared) >= WAN_MAX_REF_IMAGES:
            break
    return prepared


def _local_ref_to_data_uri(path: Path) -> str | None:
    if not path.is_file():
        return None
    payload = path.read_bytes()
    if not payload:
        return None
    flattened = _flatten_image_bytes(payload)
    if flattened is None:
        encoded = base64.b64encode(payload).decode("ascii")
        return f"data:{_guess_mime(path)};base64,{encoded}"
    body, mime = flattened
    return _bytes_to_data_uri(body, mime)


def resolve_ref_uri_for_api(
    uri: str,
    *,
    store: CharpassStore | None = None,
    entity_id: str | None = None,
) -> str | None:
    cleaned = str(uri or "").strip()
    if not cleaned:
        return None
    if is_api_ready_ref_uri(cleaned):
        return cleaned
    if store is None or not entity_id:
        return None

    rel = cleaned.replace("\\", "/").lstrip("/")
    candidates = [
        store.entity_dir(entity_id) / rel,
        store.entity_dir(entity_id) / "assets" / rel.removeprefix("assets/"),
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        data_uri = _local_ref_to_data_uri(resolved)
        if data_uri:
            return data_uri
    return None


def normalize_ref_uris_for_api(
    uris: list[str],
    *,
    store: CharpassStore | None = None,
    entity_id: str | None = None,
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for uri in uris:
        resolved = resolve_ref_uri_for_api(uri, store=store, entity_id=entity_id)
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        normalized.append(resolved)
    return normalized


WAN_MAX_REF_IMAGES = 9

_ANGLE_PRIORITY = {
    "front": 0,
    "three_quarter": 1,
    "face_detail": 2,
    "left": 3,
    "right": 4,
    "back": 5,
    "top": 6,
    "bottom": 7,
}


def provider_ref_image_limit(provider: str) -> int | None:
    if str(provider or "").strip().lower() == "wan":
        return WAN_MAX_REF_IMAGES
    return None


def _manifest_ref_meta(manifest: dict | None) -> dict[str, dict]:
    if not isinstance(manifest, dict):
        return {}
    meta_by_uri: dict[str, dict] = {}

    def _collect(items: object) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            uri = str(item.get("uri") or item.get("path") or "").strip()
            if uri:
                meta_by_uri[uri] = item

    identity = manifest.get("_identity")
    style = manifest.get("_style")
    if isinstance(identity, dict):
        _collect(identity.get("ref_images"))
    if isinstance(style, dict):
        _collect(style.get("reference_images"))
        outfit = style.get("outfit")
        if isinstance(outfit, dict):
            _collect(outfit.get("ref_images"))
    return meta_by_uri


def cap_ref_uris_for_api(
    uris: list[str],
    *,
    provider: str,
    manifest: dict | None = None,
    preferred_angle: str | None = None,
) -> list[str]:
    """依 provider 上限裁剪參考圖；WAN 最後一則 message 最多 9 張圖。"""
    limit = provider_ref_image_limit(provider)
    if limit is None or len(uris) <= limit:
        return uris

    meta_by_uri = _manifest_ref_meta(manifest)
    preferred = str(preferred_angle or "").strip()

    def keep_score(index: int, uri: str) -> tuple[int, int]:
        meta = meta_by_uri.get(uri, {})
        angle = str(meta.get("angle") or "").strip()
        note = str(meta.get("note") or "").strip()
        priority = 1000 + index
        if note == "age_span_lock":
            priority -= 800
        if preferred and angle == preferred:
            priority -= 400
        angle_rank = _ANGLE_PRIORITY.get(angle, 9)
        priority -= (10 - min(angle_rank, 9)) * 10
        return (priority, index)

    ranked = sorted(range(len(uris)), key=lambda i: keep_score(i, uris[i]))
    keep_indices = set(ranked[:limit])
    return [uri for i, uri in enumerate(uris) if i in keep_indices]
