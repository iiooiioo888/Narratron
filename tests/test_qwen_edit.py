"""Qwen-Image-Edit-2511 provider／LoRA／路由測試。"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from characteros.imaging.base import ImageGenRequest
from characteros.imaging.prompt import assemble_request
from characteros.imaging.providers.qwen_edit import (
    QwenEditImageProvider,
    _extract_edit_payload,
    _parse_gradio_sse,
    uris_to_b64_json,
)
from characteros.imaging.qwen_edit_adapters import (
    ADAPTER_SPECS,
    build_edit_prompt,
    infer_style_lora,
    list_loras,
    normalize_lora,
    pick_lora_for_request,
)
from characteros.imaging.ref_uris import cap_ref_uris_for_api, provider_ref_image_limit
from characteros.imaging.registry import get_provider, list_providers
from characteros.main import app as characteros_app
from narratron.charpass.schema import empty_manifest_dict


_TINY_PNG = bytes.fromhex(
    "89504E470D0A1A0A"
    "0000000D49484452000000010000000108060000001F15C489"
    "0000000D49444154789C6360606060000000050001A5F64540"
    "0000000049454E44AE426082"
)
_TINY_DATA_URI = "data:image/png;base64," + base64.b64encode(_TINY_PNG).decode("ascii")


def test_qwen_edit_registered_in_providers() -> None:
    names = {item["name"] for item in list_providers()}
    assert "qwen_edit" in names
    provider = get_provider("qwen_edit", base_url="http://127.0.0.1:7860")
    assert provider.name == "qwen_edit"


def test_lora_registry_covers_upstream_adapters() -> None:
    items = list_loras()
    assert len(items) >= 19
    names = {item["name"] for item in items}
    assert "Multiple-Angles" in names
    assert "Photo-to-Anime" in names
    assert "Anime-V2" in names
    assert "Pixar-Inspired-3D" in names
    assert normalize_lora("anime-v2") == "Anime-V2"
    assert normalize_lora("unknown-xyz") == "Photo-to-Anime"


def test_style_and_angle_lora_picking() -> None:
    assert infer_style_lora("可愛風格 吉卜力 公主風") == "Anime-V2"
    assert infer_style_lora("pixar 3d render") == "Pixar-Inspired-3D"
    assert pick_lora_for_request(angle="left", multi_angle=True) == "Multiple-Angles"
    assert pick_lora_for_request(purpose="thumb") == "Upscaler"
    assert pick_lora_for_request(explicit_lora="Manga-Tone") == "Manga-Tone"
    prompt = build_edit_prompt(prompt="", angle="right", lora="Multiple-Angles", multi_angle=True)
    assert "right" in prompt.lower() or "90" in prompt
    assert "identity" in prompt.lower()


def test_assemble_request_carries_style_hints_and_lora() -> None:
    data = empty_manifest_dict()
    data["_identity"]["name"] = "艾莉絲"
    data["_style"]["character_style"]["visual"]["medium"] = "anime"
    data["_style"]["character_style"]["visual"]["aesthetic"] = "可愛公主風"
    data["_style"]["character_style"]["visual"]["keywords"] = ["ghibli", "storybook"]
    req = assemble_request(
        data,
        purpose="identity",
        angle="three_quarter",
        multi_angle=True,
        extra_fields={"lora": "Fal-Multiple-Angles"},
    )
    assert "ghibli" in str(req.extra.get("style_hints") or "").lower() or "anime" in str(
        req.extra.get("style_hints") or ""
    ).lower()
    assert req.extra.get("lora") == "Fal-Multiple-Angles"
    assert req.extra.get("angle") == "three_quarter"


def test_qwen_edit_ref_limit() -> None:
    assert provider_ref_image_limit("qwen_edit") == 2
    uris = [f"https://example.com/{i}.png" for i in range(5)]
    capped = cap_ref_uris_for_api(uris, provider="qwen_edit")
    assert len(capped) == 2


def test_uris_to_b64_json_from_data_uri() -> None:
    payload = uris_to_b64_json([_TINY_DATA_URI])
    decoded = json.loads(payload)
    assert len(decoded) == 1
    assert decoded[0].startswith("data:image/png;base64,")


def test_uris_to_b64_json_requires_image() -> None:
    with pytest.raises(RuntimeError, match="至少一張"):
        uris_to_b64_json([])


def test_queue_image_request_carries_lora() -> None:
    from characteros.models.schema import ImageQueueRequest
    from characteros.services.age_span import prepare_queued_image_generation
    from characteros.services.image_pipeline import _build_single_evolution_params

    body = ImageQueueRequest(
        purpose="identity",
        provider="qwen_edit",
        lora="Anime-V2",
        multi_angle=True,
    )
    params = _build_single_evolution_params(body)
    image_request = params["_image_request"]
    assert image_request["lora"] == "Anime-V2"
    prepared = prepare_queued_image_generation({}, image_request)
    assert prepared["extra_fields"]["lora"] == "Anime-V2"


def test_extract_edit_payload_variants() -> None:
    assert _extract_edit_payload({"image": _TINY_DATA_URI, "seed": 7})["seed"] == 7
    assert _extract_edit_payload({"data": [{"image": _TINY_DATA_URI}]})["image"] == _TINY_DATA_URI
    assert _extract_edit_payload({"data": [_TINY_DATA_URI]})["image"] == _TINY_DATA_URI


def test_parse_gradio_sse_complete() -> None:
    sse = (
        "event: complete\n"
        f'data: [{{"image": "{_TINY_DATA_URI}", "seed": 42}}]\n\n'
    )
    parsed = _parse_gradio_sse(sse)
    assert parsed is not None
    assert "data" in parsed


def test_qwen_edit_provider_calls_narratron_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    class _FakeResponse:
        def __init__(self, status_code: int, body: dict) -> None:
            self.status_code = status_code
            self._body = body
            self.headers = {"content-type": "application/json"}
            self.text = json.dumps(body)

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self) -> dict:
            return self._body

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, url: str, headers=None, json=None):  # noqa: A002
            calls.append({"url": url, "json": json})
            if url.endswith("/edit"):
                return _FakeResponse(
                    200,
                    {"image": _TINY_DATA_URI, "seed": 99},
                )
            return _FakeResponse(404, {"detail": "missing"})

        def get(self, url: str, headers=None):
            return _FakeResponse(404, {})

    import httpx as httpx_mod

    monkeypatch.setattr(httpx_mod, "Client", _FakeClient)

    provider = QwenEditImageProvider(base_url="http://qwen.test:7860")
    result = provider.generate(
        ImageGenRequest(
            purpose="identity",
            prompt="front view",
            ref_image_uris=[_TINY_DATA_URI],
            extra={"angle": "front", "multi_angle": True, "filename_prefix": "id_front"},
        )
    )
    assert result.provider == "qwen_edit"
    assert len(result.images) == 1
    assert result.images[0].data == _TINY_PNG
    assert result.images[0].metadata.get("lora") == "Multiple-Angles"
    assert any(call["url"].endswith("/edit") for call in calls)
    assert calls[0]["json"]["lora_adapter"] == "Multiple-Angles"


def test_imaging_qwen_edit_loras_route() -> None:
    client = TestClient(characteros_app)
    resp = client.get("/api/v1/imaging/qwen-edit/loras")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert any(item["name"] == "Multiple-Angles" for item in body)
    assert set(ADAPTER_SPECS) <= {item["name"] for item in body}


def test_imaging_qwen_edit_route_with_mock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from narratron.charpass.store import CharpassStore

    store = CharpassStore(tmp_path / "charpasses")
    entity_id = "character-艾莉絲"
    manifest = empty_manifest_dict()
    manifest["_identity"]["name"] = "艾莉絲"
    manifest["_meta"]["entity_id"] = entity_id
    manifest["_identity"]["ref_images"] = [{"path": "assets/identity/ref.png", "uri": _TINY_DATA_URI}]
    store.write_manifest(entity_id, manifest)

    class _StubProvider:
        name = "qwen_edit"
        display_name = "stub"

        def edit(self, **kwargs):
            from characteros.imaging.base import GeneratedImage, ImageGenResult

            return ImageGenResult(
                provider="qwen_edit",
                model="Qwen-Image-Edit-2511",
                images=[
                    GeneratedImage(
                        filename="qwen_edit_001.png",
                        mime_type="image/png",
                        data=_TINY_PNG,
                        metadata={"lora": kwargs.get("lora"), "seed": 3},
                    )
                ],
                raw={"ok": True},
            )

    monkeypatch.setattr(
        "characteros.routers.imaging.get_provider",
        lambda *args, **kwargs: _StubProvider(),
    )
    monkeypatch.setattr(
        "characteros.routers.imaging.CharpassStore",
        lambda: store,
    )

    client = TestClient(characteros_app)
    resp = client.post(
        "/api/v1/imaging/qwen-edit",
        json={
            "prompt": "Transform into anime.",
            "lora": "Anime-V2",
            "entity_id": entity_id,
            "steps": 4,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "qwen_edit"
    assert body["lora"] == "Anime-V2"
    assert body["images"][0]["has_bytes"] is True


def test_imaging_qwen_edit_requires_refs() -> None:
    client = TestClient(characteros_app)
    resp = client.post(
        "/api/v1/imaging/qwen-edit",
        json={"prompt": "Transform into anime.", "lora": "Photo-to-Anime"},
    )
    assert resp.status_code == 400
