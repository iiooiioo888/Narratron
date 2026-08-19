"""CharacterOS 第三方生圖路由。"""

from fastapi import APIRouter, HTTPException, status

from characteros.imaging.registry import list_providers
from characteros.models.schema import (
    ImageGenerateRequest,
    ImageGenerateResponse,
    ImageProviderInfo,
)
from characteros.services.imaging import ImagingService
from narratron.charpass.store import CharpassStore

router = APIRouter(prefix="/api/v1/imaging", tags=["Imaging"])


@router.get("/providers", response_model=list[ImageProviderInfo])
def get_image_providers():
    """列出可插拔生圖 provider（null / http / openai / wan）。"""
    return [ImageProviderInfo(**item) for item in list_providers()]


@router.post("/generate", response_model=ImageGenerateResponse)
def generate_character_image(body: ImageGenerateRequest):
    """依角色護照組提示詞，呼叫第三方生圖 API。

    - 傳 ``entity_id``：讀本機 ``data/charpasses/{entity_id}/current.charpass``
    - 傳 ``manifest``：直接使用請求內嵌護照
    - ``provider=null``：不打網路，只回組好的提示詞（預設）
    """
    store = CharpassStore()
    manifest = body.manifest
    if manifest is None and body.entity_id:
        loaded = store.read_current_manifest(body.entity_id)
        if loaded is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"本機護照不存在：{body.entity_id}",
            )
        manifest = loaded
    if not isinstance(manifest, dict) or not manifest:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="請提供 manifest 或有效的 entity_id",
        )
    persist_id = body.entity_id if body.persist else None
    if body.persist and not persist_id:
        persist_id = str(
            (manifest.get("_meta") or {}).get("entity_id")
            or (manifest.get("_identity") or {}).get("entity_id")
            or ""
        ) or None
        if not persist_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="persist=true 時需要 entity_id",
            )
    try:
        payload = ImagingService(store).generate_for_manifest(
            manifest,
            purpose=body.purpose,
            provider_name=body.provider,
            extra=body.extra,
            n=body.n,
            model=body.model or "",
            persist_entity_id=persist_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ImageGenerateResponse.model_validate(payload)
