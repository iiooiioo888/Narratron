"""第三方生圖 provider 契約。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ImageGenRequest(BaseModel):
    """一次生圖請求。prompt 已由 `_style.character_style` 組裝完成。"""

    purpose: str = "identity"
    prompt: str
    negative_prompt: str = ""
    size: str = "1024x1024"
    n: int = 1
    model: str = ""
    ref_image_uris: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class GeneratedImage(BaseModel):
    """單張產出。bytes 與 URL 擇一即可。"""

    filename: str
    mime_type: str = "image/png"
    data: bytes | None = None
    url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageGenResult(BaseModel):
    provider: str
    model: str = ""
    images: list[GeneratedImage] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class ImageGenProvider(ABC):
    """可插拔生圖後端。實作只負責呼叫第三方 API，不讀改 `_extensions`。"""

    name: str
    display_name: str = ""

    @abstractmethod
    def generate(self, request: ImageGenRequest) -> ImageGenResult:
        raise NotImplementedError
