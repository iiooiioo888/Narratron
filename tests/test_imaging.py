"""角色風格組 prompt 與 CharacterOS 可插拔生圖。"""

from __future__ import annotations

from pathlib import Path

from characteros.imaging.prompt import assemble_request
from characteros.imaging.registry import get_provider, list_providers
from characteros.services.imaging import ImagingService, apply_result_to_manifest
from narratron.charpass.schema import empty_manifest_dict, manifest_to_dict
from narratron.charpass.store import CharpassStore
from narratron.charpass.style_prompt import build_image_prompt, build_narrative_prompt


def _styled_manifest() -> dict:
    data = empty_manifest_dict()
    data["_identity"]["name"] = "卡爾"
    data["_meta"]["entity_id"] = "character-卡爾"
    data["_style"]["outfit"]["description"] = "舊白色亞麻襯衫"
    data["_style"]["character_style"] = {
        "visual": {
            "medium": "cinematic realism",
            "aesthetic": "冷調都市",
            "color_palette": ["#1B1F2A"],
            "lighting": "側光",
            "camera": "50mm",
            "keywords": ["weathered"],
        },
        "art_prompt": {
            "positive": "highly detailed face",
            "negative": "cartoon, watermark",
            "strength": 1.0,
        },
        "narrative": {
            "tone": "克制",
            "speech_pattern": "短句",
            "sample_lines": ["……我知道了。"],
        },
        "consistency_notes": "臉必須一致",
    }
    data["_identity"]["ref_images"] = [{"path": "assets/identity/ref_face_001.jpg", "uri": "file://face"}]
    return data


def test_empty_manifest_includes_character_style() -> None:
    data = empty_manifest_dict()
    style = data["_style"]["character_style"]
    assert "visual" in style
    assert "art_prompt" in style
    assert "narrative" in style
    assert data["_extensions"]["image_gen"]["provider"] == ""


def test_build_image_prompt_includes_style_and_outfit() -> None:
    prompt = build_image_prompt(_styled_manifest(), purpose="identity")
    assert "卡爾" in prompt["positive"]
    assert "cinematic realism" in prompt["positive"]
    assert "舊白色亞麻襯衫" in prompt["positive"]
    assert "highly detailed face" in prompt["positive"]
    assert prompt["negative"] == "cartoon, watermark"


def test_build_narrative_prompt() -> None:
    text = build_narrative_prompt(_styled_manifest())
    assert "卡爾" in text
    assert "克制" in text
    assert "我知道了" in text


def test_unknown_style_fields_roundtrip() -> None:
    data = _styled_manifest()
    data["_style"]["character_style"]["visual"]["custom_lens"] = "anamorphic"
    dumped = manifest_to_dict(data)
    assert dumped["_style"]["character_style"]["visual"]["custom_lens"] == "anamorphic"


def test_null_provider_dry_run(tmp_path: Path) -> None:
    names = {item["name"] for item in list_providers()}
    assert names == {"null", "http", "openai", "wan"}
    service = ImagingService(store=CharpassStore(tmp_path))
    payload = service.generate_for_manifest(
        _styled_manifest(),
        purpose="identity",
        provider_name="null",
        persist_entity_id="character-卡爾",
    )
    assert payload["provider"] == "null"
    assert "卡爾" in payload["prompt"]
    assert payload["images"][0]["filename"].startswith("ref_face_")
    assert payload["manifest"]["_identity"]["ref_images"][-1]["path"].startswith("assets/identity/")
    assert payload["manifest"]["_extensions"]["image_gen"]["provider"] == "null"
    stored = service.store.read_current_manifest("character-卡爾")
    assert stored is not None
    assert stored["_extensions"]["image_gen"]["last_job_id"]


def test_outfit_purpose_writes_style_refs() -> None:
    request = assemble_request(_styled_manifest(), purpose="outfit")
    result = get_provider("null").generate(request)
    updated = apply_result_to_manifest(_styled_manifest(), request, result)
    refs = updated["_style"]["outfit"]["ref_images"]
    assert refs
    assert refs[-1]["path"].startswith("assets/style/")


def test_wan_url_and_size_helpers() -> None:
    from characteros.imaging.providers.wan import normalize_wan_size, resolve_wan_generation_url

    url = resolve_wan_generation_url(
        "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    assert url.endswith("/api/v1/services/aigc/multimodal-generation/generation")
    assert normalize_wan_size("1024x1024") == "1K"
    assert normalize_wan_size("2K") == "2K"


def test_wan_provider_parses_response(monkeypatch) -> None:
    from characteros.imaging.base import ImageGenRequest
    from characteros.imaging.providers.wan import WanImageProvider

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "output": {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"type": "image", "image": "https://example.com/out.png"},
                                ]
                            }
                        }
                    ]
                }
            }

    def fake_post(url, **kwargs):
        assert url.endswith("/api/v1/services/aigc/multimodal-generation/generation")
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"
        body = kwargs["json"]
        assert body["model"] == "wan2.7-image-pro"
        assert body["input"]["messages"][0]["content"][-1]["text"]
        assert body["parameters"]["size"] == "1K"
        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)

    provider = WanImageProvider(api_key="test-key")
    result = provider.generate(
        ImageGenRequest(
            purpose="identity",
            prompt="卡爾, human, cinematic realism",
            size="1024x1024",
            model="wan2.7-image-pro",
            extra={"filename_prefix": "ref_face"},
        )
    )
    assert result.provider == "wan"
    assert result.images[0].url == "https://example.com/out.png"
    assert result.images[0].filename == "ref_face_001.png"

