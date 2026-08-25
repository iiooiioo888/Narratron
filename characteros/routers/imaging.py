"""CharacterOS 第三方生圖／圖編路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from characteros.imaging.qwen_edit_adapters import list_loras, normalize_lora
from characteros.imaging.ref_uris import normalize_ref_uris_for_api
from characteros.imaging.registry import get_provider, list_providers
from characteros.models.schema import (
    GeneratedImageInfo,
    ImageProviderInfo,
    QwenEditLoraInfo,
    QwenEditRequest,
    QwenEditResponse,
)
from narratron.charpass.store import CharpassStore
from narratron.charpass.style_prompt import collect_ref_image_uris

router = APIRouter(prefix="/api/v1/imaging", tags=["Imaging"])


@router.get("/providers", response_model=list[ImageProviderInfo])
def get_image_providers():
    """列出可插拔生圖 provider（null / http / openai / wan / qwen_edit）。"""
    return [ImageProviderInfo(**item) for item in list_providers()]


@router.get("/qwen-edit/loras", response_model=list[QwenEditLoraInfo])
def get_qwen_edit_loras():
    """列出 Qwen-Image-Edit-2511 懶載入 LoRA（對齊上游 ADAPTER_SPECS）。"""
    return [QwenEditLoraInfo(**item) for item in list_loras()]


@router.post("/qwen-edit", response_model=QwenEditResponse)
def post_qwen_edit(body: QwenEditRequest):
    """呼叫 Qwen Image Edit（多角度／風格／超分）。

    需本機或遠端已啟動上游服務：
    https://github.com/PRITHIVSAKTHIUR/Qwen-Image-Edit-2511-LoRAs-Fast-Lazy-Load
    """
    store = CharpassStore()
    ref_uris = [str(uri).strip() for uri in (body.ref_image_uris or []) if str(uri).strip()]
    entity_id = str(body.entity_id or "").strip() or None

    if entity_id:
        manifest = store.read_current_manifest(entity_id)
        if not isinstance(manifest, dict) or not manifest:
            raise HTTPException(status_code=404, detail=f"找不到護照：{entity_id}")
        seed = collect_ref_image_uris(manifest)
        for uri in seed:
            cleaned = str(uri or "").strip()
            if cleaned and cleaned not in ref_uris:
                ref_uris.append(cleaned)
        ref_uris = normalize_ref_uris_for_api(ref_uris, store=store, entity_id=entity_id)

    if not ref_uris:
        raise HTTPException(
            status_code=400,
            detail="需要至少一張參考圖：請傳 ref_image_uris，或指定已有身份圖的 entity_id",
        )

    lora = normalize_lora(body.lora)
    try:
        provider = get_provider(
            "qwen_edit",
            base_url=body.base_url,
            api_key=body.api_key,
            model=body.model,
        )
        result = provider.edit(  # type: ignore[attr-defined]
            ref_image_uris=ref_uris,
            prompt=body.prompt,
            lora=lora,
            seed=body.seed,
            randomize_seed=body.randomize_seed,
            guidance_scale=body.guidance_scale,
            steps=body.steps,
            filename_prefix=body.purpose or "qwen_edit",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    images = [
        GeneratedImageInfo(
            filename=image.filename,
            url=image.url,
            has_bytes=image.data is not None,
            mime_type=image.mime_type,
            angle=(image.metadata or {}).get("angle") if isinstance(image.metadata, dict) else None,
        )
        for image in result.images
    ]
    seed_value: int | None = None
    if result.images and isinstance(result.images[0].metadata, dict):
        raw_seed = result.images[0].metadata.get("seed")
        if raw_seed is not None:
            try:
                seed_value = int(raw_seed)
            except (TypeError, ValueError):
                seed_value = None

    # 可選：寫回護照（僅 bytes 時）
    if body.persist and entity_id:
        _persist_edit_result(store, entity_id, body, result)

    raw: dict[str, Any] = result.raw if isinstance(result.raw, dict) else {"raw": result.raw}
    return QwenEditResponse(
        provider=result.provider,
        model=result.model,
        lora=lora,
        seed=seed_value,
        prompt=body.prompt,
        images=images,
        raw=raw,
    )


def _persist_edit_result(store: CharpassStore, entity_id: str, body: QwenEditRequest, result: Any) -> None:
    from characteros.imaging.base import ImageGenRequest
    from characteros.services.imaging import ImagingService, apply_result_to_manifest

    manifest = store.read_current_manifest(entity_id)
    if not isinstance(manifest, dict):
        return
    request = ImageGenRequest(
        purpose=body.purpose or "edit",
        prompt=body.prompt,
        ref_image_uris=list(body.ref_image_uris or []),
        extra={
            "filename_prefix": body.purpose or "qwen_edit",
            "lora": body.lora,
            "asset_dir": "assets/edit",
        },
    )
    service = ImagingService(store=store)
    service._download_remote_assets(result)  # noqa: SLF001
    updated = apply_result_to_manifest(manifest, request, result)
    assets = {
        f"assets/edit/{image.filename}": image.data
        for image in result.images
        if image.data
    }
    if assets:
        store.write_assets(entity_id, assets)
    store.write_manifest(entity_id, updated)
