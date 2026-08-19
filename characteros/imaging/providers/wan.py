"""阿里雲百煉 WAN 2.7 生圖（原生 multimodal-generation API，非 OpenAI /images）。"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from characteros.imaging.base import GeneratedImage, ImageGenProvider, ImageGenRequest, ImageGenResult
from characteros.imaging.settings import settings

WAN_GENERATION_PATH = "/api/v1/services/aigc/multimodal-generation/generation"

_SIZE_TO_WAN = {
    "1024x1024": "1K",
    "1024*1024": "1K",
    "2048x2048": "2K",
    "2048*2048": "2K",
    "4096x4096": "4K",
    "4096*4096": "4K",
}


def resolve_wan_generation_url(base_url: str) -> str:
    """把 compatible-mode base 或 workspace 根網址解析成 WAN 生圖 endpoint。"""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        base = settings.get_base_url().rstrip("/")

    for suffix in ("/compatible-mode/v1", "/compatible-mode"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break

    if base.endswith(WAN_GENERATION_PATH):
        return base

    parsed = urlparse(base)
    if parsed.path and parsed.path not in {"", "/"}:
        root = f"{parsed.scheme}://{parsed.netloc}"
        return f"{root.rstrip('/')}{WAN_GENERATION_PATH}"

    return f"{base}{WAN_GENERATION_PATH}"


def normalize_wan_size(size: str) -> str:
    cleaned = (size or "2K").strip()
    upper = cleaned.upper()
    if upper in {"1K", "2K", "4K"}:
        return upper
    mapped = _SIZE_TO_WAN.get(cleaned.lower()) or _SIZE_TO_WAN.get(cleaned)
    return mapped or "2K"


def _build_content(prompt: str, ref_image_uris: list[str]) -> list[dict[str, str]]:
    content: list[dict[str, str]] = []
    for uri in ref_image_uris:
        cleaned = str(uri).strip()
        if cleaned:
            content.append({"image": cleaned})
    content.append({"text": prompt})
    return content


def _parse_wan_images(body: Any, *, filename_prefix: str) -> list[GeneratedImage]:
    if not isinstance(body, dict):
        raise RuntimeError("WAN 生圖回應不是 JSON 物件")

    output = body.get("output")
    if not isinstance(output, dict):
        raise RuntimeError("WAN 生圖回應缺少 output")

    choices = output.get("choices")
    if not isinstance(choices, list):
        raise RuntimeError("WAN 生圖回應缺少 output.choices")

    images: list[GeneratedImage] = []
    index = 0
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        for item in message.get("content") or []:
            if not isinstance(item, dict):
                continue
            url = item.get("image") or item.get("url")
            if not url:
                continue
            index += 1
            images.append(
                GeneratedImage(
                    filename=f"{filename_prefix}_{index:03d}.png",
                    mime_type="image/png",
                    url=str(url),
                    metadata={"type": item.get("type") or "image"},
                )
            )

    if not images:
        code = body.get("code") or output.get("code")
        message = body.get("message") or output.get("message") or body.get("error")
        detail = f" ({code}: {message})" if code or message else ""
        raise RuntimeError(f"WAN 生圖回應沒有圖片{detail}")
    return images


class WanImageProvider(ImageGenProvider):
    name = "wan"
    display_name = "WAN 2.7（百煉原生 API）"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        self.api_key = (
            api_key
            or settings.get_api_key()
            or os.environ.get("OPENAI_API_KEY", "")
        )
        self.base_url = base_url or settings.get_base_url()
        self.default_model = model or settings.get_model()
        self.timeout_s = timeout_s

    def generate(self, request: ImageGenRequest) -> ImageGenResult:
        if not self.api_key:
            raise RuntimeError("未設定 CHARACTEROS_IMAGE_GEN_API_KEY（或 OPENAI_API_KEY）")
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("WAN provider 需要 httpx：pip install httpx") from exc

        model = request.model or self.default_model
        endpoint = resolve_wan_generation_url(self.base_url)
        parameters: dict[str, Any] = {
            "size": normalize_wan_size(request.size),
            "n": request.n,
            "watermark": False,
        }
        if request.negative_prompt:
            parameters["negative_prompt"] = request.negative_prompt

        payload = {
            "model": model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": _build_content(request.prompt, request.ref_image_uris),
                    }
                ]
            },
            "parameters": parameters,
        }

        response = httpx.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_s,
        )
        response.raise_for_status()
        body = response.json()
        prefix = str(request.extra.get("filename_prefix") or request.purpose)
        images = _parse_wan_images(body, filename_prefix=prefix)
        return ImageGenResult(provider=self.name, model=model, images=images, raw=body)
