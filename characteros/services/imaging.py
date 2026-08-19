"""把第三方生圖結果寫回角色護照（資產路徑 + `_extensions.image_gen`）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from characteros.imaging.base import ImageGenRequest, ImageGenResult
from characteros.imaging.prompt import assemble_request
from characteros.imaging.registry import get_provider
from narratron.charpass.schema import manifest_to_dict
from narratron.charpass.style_prompt import PURPOSE_SLOTS
from narratron.charpass.store import CharpassStore


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def apply_result_to_manifest(
    manifest: dict[str, Any],
    request: ImageGenRequest,
    result: ImageGenResult,
) -> dict[str, Any]:
    """把產出圖的路徑／URL 寫入對應層；核心仍不呼叫 generate。"""

    data = manifest_to_dict(manifest)
    slot = PURPOSE_SLOTS.get(request.purpose, PURPOSE_SLOTS["identity"])
    asset_dir = str(request.extra.get("asset_dir") or slot["asset_dir"])
    job_id = str(uuid4())
    refs: list[dict[str, Any]] = []
    for image in result.images:
        path = f"{asset_dir}/{image.filename}"
        refs.append(
            {
                "path": path,
                "uri": image.url or path,
                "kind": "reference_image",
                "note": f"generated:{result.provider}:{request.purpose}",
            }
        )

    style = data.setdefault("_style", {})
    identity = data.setdefault("_identity", {})
    if request.purpose == "identity":
        identity.setdefault("ref_images", []).extend(refs)
    elif request.purpose == "outfit":
        outfit = style.setdefault("outfit", {})
        outfit.setdefault("ref_images", []).extend(refs)
    else:
        style.setdefault("reference_images", []).extend(refs)

    extensions = data.setdefault("_extensions", {})
    image_gen = extensions.setdefault("image_gen", {})
    image_gen["provider"] = result.provider
    image_gen["model"] = result.model
    image_gen["last_job_id"] = job_id
    image_gen["last_asset_paths"] = [item["path"] for item in refs]
    image_gen["size"] = request.size
    meta = data.setdefault("_meta", {})
    meta["updated_at"] = _utcnow()
    return data


class ImagingService:
    """CharacterOS 生圖編排：組 prompt → provider.generate → 可選寫回本機護照。"""

    def __init__(self, store: CharpassStore | None = None) -> None:
        self.store = store or CharpassStore()

    def generate_for_manifest(
        self,
        manifest: dict[str, Any],
        *,
        purpose: str = "identity",
        provider_name: str | None = None,
        extra: str = "",
        n: int = 1,
        model: str = "",
        base_url: str = "",
        api_key: str = "",
        persist_entity_id: str | None = None,
    ) -> dict[str, Any]:
        request = assemble_request(manifest, purpose=purpose, extra=extra, n=n, model=model)
        provider = get_provider(
            provider_name,
            model=(model or None),
            base_url=(base_url or None),
            api_key=(api_key or None),
        )
        result = provider.generate(request)
        updated = apply_result_to_manifest(manifest, request, result)
        entity_id = persist_entity_id or ""
        if entity_id:
            assets = {
                f"{request.extra.get('asset_dir')}/{image.filename}": image.data
                for image in result.images
                if image.data
            }
            if assets:
                self.store.write_assets(entity_id, assets)
            self.store.write_manifest(entity_id, updated)
        return {
            "provider": result.provider,
            "model": result.model,
            "purpose": purpose,
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "ref_image_uris": request.ref_image_uris,
            "images": [
                {
                    "filename": image.filename,
                    "url": image.url,
                    "has_bytes": image.data is not None,
                    "mime_type": image.mime_type,
                }
                for image in result.images
            ],
            "manifest": updated,
        }
