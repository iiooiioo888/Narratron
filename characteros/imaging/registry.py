"""依名稱解析生圖 provider。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from characteros.imaging.base import ImageGenProvider
from characteros.imaging.providers.http_webhook import HttpWebhookImageProvider
from characteros.imaging.providers.null import NullImageProvider
from characteros.imaging.providers.openai_images import OpenAIImagesProvider
from characteros.imaging.providers.wan import WanImageProvider
from characteros.imaging.settings import settings

_FACTORY: dict[str, Callable[..., ImageGenProvider]] = {
    "null": NullImageProvider,
    "http": HttpWebhookImageProvider,
    "openai": OpenAIImagesProvider,
    "wan": WanImageProvider,
}


def list_providers() -> list[dict[str, str]]:
    samples = {
        "null": NullImageProvider(),
        "http": HttpWebhookImageProvider(),
        "openai": OpenAIImagesProvider(),
        "wan": WanImageProvider(),
    }
    return [
        {"name": item.name, "display_name": item.display_name}
        for item in samples.values()
    ]


def get_provider(name: str | None = None, **kwargs: Any) -> ImageGenProvider:
    resolved = (name or settings.get_provider() or "null").strip().lower()
    factory = _FACTORY.get(resolved)
    if factory is None:
        known = ", ".join(sorted(_FACTORY))
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
