"""OpenAI Images 相容端點（官方 API 或第三方相容閘道）。"""

from __future__ import annotations

import os
from typing import Any

from characteros.imaging.base import GeneratedImage, ImageGenProvider, ImageGenRequest, ImageGenResult
from characteros.imaging.settings import settings


class OpenAIImagesProvider(ImageGenProvider):
    name = "openai"
    display_name = "OpenAI Images（相容閘道）"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: float = 90.0,
    ) -> None:
        self.api_key = (
            api_key
            or settings.get_api_key()
            or os.environ.get("OPENAI_API_KEY", "")
        )
        self.base_url = (base_url or settings.get_base_url()).rstrip("/")
        self.default_model = model or settings.get_model()
        self.timeout_s = timeout_s

    def generate(self, request: ImageGenRequest) -> ImageGenResult:
        if not self.api_key:
            raise RuntimeError("未設定 CHARACTEROS_IMAGE_GEN_API_KEY（或 OPENAI_API_KEY）")
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("OpenAI provider 需要 httpx：pip install httpx") from exc

        model = request.model or self.default_model
        payload: dict[str, Any] = {
            "model": model,
            "prompt": request.prompt,
            "n": request.n,
            "size": request.size,
        }
        if request.negative_prompt:
            payload["extra"] = {"negative_prompt": request.negative_prompt}
        if request.ref_image_uris:
            payload["extra"] = {**(payload.get("extra") or {}), "ref_image_uris": request.ref_image_uris}

        response = httpx.post(
            f"{self.base_url}/images/generations",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=self.timeout_s,
        )
        response.raise_for_status()
        body = response.json()
        prefix = str(request.extra.get("filename_prefix") or request.purpose)
        images: list[GeneratedImage] = []
        for index, item in enumerate(body.get("data") or [], start=1):
            if not isinstance(item, dict):
                continue
            b64 = item.get("b64_json")
            url = item.get("url")
            data = None
            if b64:
                import base64

                data = base64.b64decode(str(b64))
            images.append(
                GeneratedImage(
                    filename=f"{prefix}_{index:03d}.png",
                    mime_type="image/png",
                    data=data,
                    url=str(url) if url else None,
                    metadata={"revised_prompt": item.get("revised_prompt")},
                )
            )
        if not images:
            raise RuntimeError("OpenAI Images 回應沒有圖片")
        return ImageGenResult(provider=self.name, model=model, images=images, raw=body)
