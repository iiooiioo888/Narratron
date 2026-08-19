"""CharacterOS 第三方生圖路由。"""

from fastapi import APIRouter, HTTPException, status

from characteros.imaging.registry import list_providers
from characteros.models.schema import (
    ImageGenerateRequest,
    ImageGenerateResponse,
    ImageProviderInfo,
)

router = APIRouter(prefix="/api/v1/imaging", tags=["Imaging"])


@router.get("/providers", response_model=list[ImageProviderInfo])
def get_image_providers():
    """列出可插拔生圖 provider（null / http / openai / wan）。"""
    return [ImageProviderInfo(**item) for item in list_providers()]


@router.post("/generate", response_model=ImageGenerateResponse)
def generate_character_image(_: ImageGenerateRequest):
    """此入口已停用：生圖僅允許從 GUI 面板觸發。

    請改用 `/admin/panel` 內的「生成圖片」按鈕。
    """
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="`/api/v1/imaging/generate` 已停用，請使用 GUI 面板 `/admin/panel` 進行生圖。",
    )
