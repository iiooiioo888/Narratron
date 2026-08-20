"""CharacterOS 第三方生圖路由。"""

from fastapi import APIRouter

from characteros.imaging.registry import list_providers
from characteros.models.schema import ImageProviderInfo

router = APIRouter(prefix="/api/v1/imaging", tags=["Imaging"])


@router.get("/providers", response_model=list[ImageProviderInfo])
def get_image_providers():
    """列出可插拔生圖 provider（null / http / openai / wan）。"""
    return [ImageProviderInfo(**item) for item in list_providers()]
