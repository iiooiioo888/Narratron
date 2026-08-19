"""空實作：不呼叫網路，回傳提示詞 metadata，供測試與 dry-run。"""

from __future__ import annotations

from characteros.imaging.base import GeneratedImage, ImageGenProvider, ImageGenRequest, ImageGenResult


class NullImageProvider(ImageGenProvider):
    name = "null"
    display_name = "Null（不呼叫第三方）"

    def generate(self, request: ImageGenRequest) -> ImageGenResult:
        prefix = str(request.extra.get("filename_prefix") or request.purpose)
        images = [
            GeneratedImage(
                filename=f"{prefix}_{index:03d}.png",
                mime_type="image/png",
                data=None,
                url=None,
                metadata={"dry_run": True, "index": index},
            )
            for index in range(1, max(1, request.n) + 1)
        ]
        return ImageGenResult(
            provider=self.name,
            model=request.model or "null",
            images=images,
            raw={
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt,
                "ref_image_uris": request.ref_image_uris,
                "size": request.size,
            },
        )
