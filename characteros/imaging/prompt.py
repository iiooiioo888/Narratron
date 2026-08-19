"""把角色護照轉成 ImageGenRequest。"""

from __future__ import annotations

from typing import Any

from characteros.imaging.base import ImageGenRequest
from narratron.charpass.style_prompt import PURPOSE_SLOTS, build_image_prompt, collect_ref_image_uris


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
) -> ImageGenRequest:
    built = build_image_prompt(
        manifest,
        purpose=purpose,
        extra=extra,
        angle=angle,
        multi_angle=multi_angle,
    )
    extensions = manifest.get("_extensions") if isinstance(manifest.get("_extensions"), dict) else {}
    image_gen = extensions.get("image_gen") if isinstance(extensions.get("image_gen"), dict) else {}
    resolved_size = size or str(image_gen.get("size") or "1024x1024")
    resolved_model = model or str(image_gen.get("model") or "")
    slot = PURPOSE_SLOTS.get(purpose, PURPOSE_SLOTS["identity"])
    filename_prefix = slot["filename_prefix"]
    if multi_angle and angle:
        filename_prefix = f"{filename_prefix}_{angle}"
    return ImageGenRequest(
        purpose=purpose,
        prompt=built["positive"],
        negative_prompt=built["negative"],
        size=resolved_size,
        n=n,
        model=resolved_model,
        ref_image_uris=collect_ref_image_uris(manifest),
        extra={
            "asset_dir": slot["asset_dir"],
            "filename_prefix": filename_prefix,
            "angle": angle or "",
            "multi_angle": multi_angle,
        },
    )
