"""通用 HTTP webhook：POST JSON，期望回傳 URL 或 base64。"""

from __future__ import annotations

import base64
import os
from typing import Any

from characteros.imaging.base import GeneratedImage, ImageGenProvider, ImageGenRequest, ImageGenResult


def _decode_b64(payload: str) -> bytes:
    return base64.b64decode(payload)


class HttpWebhookImageProvider(ImageGenProvider):
    """對任意第三方端點 POST，契約如下。

    Request::

        {
          "prompt": "...",
          "negative_prompt": "...",
          "size": "1024x1024",
          "n": 1,
          "model": "",
          "ref_image_uris": [],
          "purpose": "identity"
        }

    Response（擇一）::

        {"images": [{"url": "https://..."}, {"b64": "...", "mime_type": "image/png"}]}
        {"url": "https://..."}
        {"b64_json": "..."}
    """

    name = "http"
    display_name = "HTTP Webhook"

    def __init__(self, endpoint: str | None = None, timeout_s: float = 60.0) -> None:
        self.endpoint = endpoint or os.environ.get("CHARACTEROS_IMAGE_GEN_ENDPOINT", "")
        self.timeout_s = timeout_s

    def generate(self, request: ImageGenRequest) -> ImageGenResult:
        if not self.endpoint:
            raise RuntimeError("未設定 HTTP 生圖端點（CHARACTEROS_IMAGE_GEN_ENDPOINT）")
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("HTTP provider 需要 httpx：pip install httpx") from exc

        payload = {
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "size": request.size,
            "n": request.n,
            "model": request.model,
            "ref_image_uris": request.ref_image_uris,
            "purpose": request.purpose,
        }
        response = httpx.post(self.endpoint, json=payload, timeout=self.timeout_s)
        response.raise_for_status()
        body: Any = response.json()
        images = _parse_images(body, request)
        return ImageGenResult(
            provider=self.name,
            model=request.model or str(body.get("model") or ""),
            images=images,
            raw=body if isinstance(body, dict) else {"body": body},
        )


def _parse_images(body: Any, request: ImageGenRequest) -> list[GeneratedImage]:
    prefix = str(request.extra.get("filename_prefix") or request.purpose)
    items: list[Any]
    if isinstance(body, dict) and isinstance(body.get("images"), list):
        items = body["images"]
    elif isinstance(body, dict):
        items = [body]
    elif isinstance(body, list):
        items = body
    else:
        raise RuntimeError("HTTP 生圖回應無法解析")

    images: list[GeneratedImage] = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, str):
            item = {"url": item}
        if not isinstance(item, dict):
            continue
        b64 = item.get("b64") or item.get("b64_json") or item.get("image_base64")
        url = item.get("url") or item.get("image_url")
        mime = str(item.get("mime_type") or "image/png")
        data = _decode_b64(str(b64)) if b64 else None
        images.append(
            GeneratedImage(
                filename=f"{prefix}_{index:03d}.png",
                mime_type=mime,
                data=data,
                url=str(url) if url else None,
                metadata={k: v for k, v in item.items() if k not in {"b64", "b64_json", "image_base64"}},
            )
        )
    if not images:
        raise RuntimeError("HTTP 生圖回應沒有圖片")
    return images
