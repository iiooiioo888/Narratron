"""把角色護照轉成 ImageGenRequest。"""

from __future__ import annotations

from typing import Any

from characteros.imaging.base import ImageGenRequest
from narratron.charpass.style_prompt import (
    PURPOSE_SLOTS,
    build_image_prompt,
    collect_ref_image_uris,
    resolve_prompt_angle,
)


def assemble_request(
    manifest: dict[str, Any],
    *,
    purpose: str = "identity",
    extra: str = "",
    size: str | None = None,
    n: int = 1,
    model: str = "",
    angle: str | None = None,
    multi_angle: bool = True,
    extra_ref_uris: list[str] | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> ImageGenRequest:
    overrides = extra_fields if isinstance(extra_fields, dict) else {}
    resolved_angle_input = str(overrides.get("angle") or angle or "").strip() or None
    built = build_image_prompt(
        manifest,
        purpose=purpose,
        extra=extra,
        angle=resolved_angle_input,
        multi_angle=multi_angle,
    )
    resolved_angle = resolve_prompt_angle(
        purpose=purpose,
        angle=resolved_angle_input,
        multi_angle=multi_angle,
    )
    extensions = manifest.get("_extensions") if isinstance(manifest.get("_extensions"), dict) else {}
    image_gen = extensions.get("image_gen") if isinstance(extensions.get("image_gen"), dict) else {}
    resolved_size = size or str(image_gen.get("size") or "1024x1024")
    resolved_model = model or str(image_gen.get("model") or "")
    slot = PURPOSE_SLOTS.get(purpose, PURPOSE_SLOTS["identity"])
    filename_prefix = str(overrides.get("filename_prefix") or slot["filename_prefix"])
    if multi_angle and resolved_angle and "filename_prefix" not in overrides:
        if not (purpose == "face_detail" and resolved_angle == "face_detail"):
            filename_prefix = f"{filename_prefix}_{resolved_angle}"
    pipeline = str(overrides.get("pipeline") or "").strip()
    extra_uris = [str(uri).strip() for uri in (extra_ref_uris or []) if str(uri).strip()]
    seed_uris: list[str] = []
    for uri in collect_ref_image_uris(manifest):
        cleaned = str(uri or "").strip()
        if not cleaned or cleaned in seed_uris:
            continue
        seed_uris.append(cleaned)

    def _https_first(uris: list[str]) -> list[str]:
        https: list[str] = []
        rest: list[str] = []
        for item in uris:
            lowered = item.lower()
            if lowered.startswith(("http://", "https://")):
                https.append(item)
            elif not lowered.startswith("file:"):
                rest.append(item)
        return https + rest

    if pipeline == "age_span":
        # 年齡軸只鎖上一步參考圖；不可再混入護照裡的成人／多視角 identity 圖。
        ref_uris = _https_first(list(extra_uris))
        age_value = overrides.get("age")
        try:
            age_number = int(age_value)
        except (TypeError, ValueError):
            age_number = 0
        if not ref_uris and age_number <= 1:
            ref_uris = _https_first(seed_uris)
    else:
        ref_uris = list(extra_uris)
        for uri in _https_first(seed_uris):
            if uri not in ref_uris:
                ref_uris.append(uri)
    extra_payload = {
        "asset_dir": str(overrides.get("asset_dir") or slot["asset_dir"]),
        "filename_prefix": filename_prefix,
        "angle": resolved_angle,
        "multi_angle": multi_angle,
    }
    for key in ("age", "pipeline", "pipeline_id"):
        if overrides.get(key) not in (None, ""):
            extra_payload[key] = overrides[key]
    return ImageGenRequest(
        purpose=purpose,
        prompt=built["positive"],
        negative_prompt=built["negative"],
        size=resolved_size,
        n=n,
        model=resolved_model,
        ref_image_uris=ref_uris,
        extra=extra_payload,
    )
