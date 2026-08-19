"""依名稱解析生圖 provider。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from characteros.imaging.base import ImageGenProvider
from characteros.imaging.settings import settings

# 延遲匯入：僅在 get_provider 實際呼叫時才載入具體實作
_FACTORY: dict[str, Callable[..., ImageGenProvider]] = {}


_PROVIDER_INFO: list[dict[str, str]] = [
    {"name": "null", "display_name": "Null（不呼叫第三方）"},
    {"name": "http", "display_name": "HTTP Webhook"},
    {"name": "openai", "display_name": "OpenAI Images"},
    {"name": "wan", "display_name": "WAN 2.7（百煉原生 API）"},
]


def list_providers() -> list[dict[str, str]]:
    """列出已註冊的生圖 provider（靜態數據，避免每次實例化）。"""
    return list(_PROVIDER_INFO)


def _get_factory() -> dict[str, Callable[..., ImageGenProvider]]:
    """延遲載入 provider 工廠（避免每次 import 都實例化）。"""
    if not _FACTORY:
        from characteros.imaging.providers.http_webhook import HttpWebhookImageProvider
        from characteros.imaging.providers.null import NullImageProvider
        from characteros.imaging.providers.openai_images import OpenAIImagesProvider
        from characteros.imaging.providers.wan import WanImageProvider
        _FACTORY.update({
            "null": NullImageProvider,
            "http": HttpWebhookImageProvider,
            "openai": OpenAIImagesProvider,
            "wan": WanImageProvider,
        })
    return _FACTORY


def get_provider(name: str | None = None, **kwargs: Any) -> ImageGenProvider:
    resolved = (name or settings.get_provider() or "null").strip().lower()
    factory = _get_factory().get(resolved)
    if factory is None:
        known = ", ".join(sorted(_get_factory()))
        raise ValueError(f"未知生圖 provider：{resolved}（可用：{known}）")
    if resolved == "http":
        endpoint = kwargs.get("base_url")
        return factory(endpoint=endpoint) if endpoint else factory()
    if resolved in {"openai", "wan"}:
        return factory(
            api_key=kwargs.get("api_key"),
            base_url=kwargs.get("base_url"),
            model=kwargs.get("model"),
        )
    return factory()
