"""角色風格組 prompt 與 CharacterOS 可插拔生圖。"""

from __future__ import annotations

import os
from pathlib import Path

from characteros.imaging.prompt import assemble_request
from characteros.imaging.registry import get_provider, list_providers
from characteros.services.imaging import (
    ImagingService,
    apply_result_to_manifest,
    finalize_reviewed_generation,
)
from narratron.charpass.schema import empty_manifest_dict, manifest_to_dict
from narratron.charpass.store import CharpassStore
from narratron.charpass.style_prompt import MULTI_VIEW_ANGLES, build_image_prompt, build_narrative_prompt


def _styled_manifest() -> dict:
    data = empty_manifest_dict()
    data["_identity"]["name"] = "卡爾"
    data["_meta"]["entity_id"] = "character-卡爾"
    data["_style"]["outfit"]["description"] = "舊白色亞麻襯衫"
    data["_style"]["hair"] = {"style": "後梳黑髮"}
    data["_style"]["additional_descriptors"] = ["lean build", "scar under left eye"]
    data["_style"]["character_style"] = {
        "visual": {
            "medium": "cinematic realism",
            "aesthetic": "冷調都市",
            "color_palette": ["#1B1F2A"],
            "lighting": "側光",
            "camera": "50mm",
            "keywords": ["weathered"],
            "note": "muted contrast",
        },
        "art_prompt": {
            "positive": "highly detailed face",
            "negative": "cartoon, watermark",
            "strength": 1.0,
            "template": "{name} reference sheet for {purpose}",
            "note": "avoid stylized exaggeration",
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
    assert "single character only" in prompt["positive"]
    assert "lean build" in prompt["positive"]
    assert "後梳黑髮" in prompt["positive"]
    assert "multi-view seven-angle layout" not in prompt["positive"]
    assert "cartoon" in prompt["negative"]
    assert "multiple characters" in prompt["negative"]
    assert "identity drift" in prompt["negative"]


def test_identity_angle_prompt_carries_style_and_single_character_rules() -> None:
    prompt = build_image_prompt(_styled_manifest(), purpose="identity", angle="front", multi_angle=True)
    assert "front view" in prompt["positive"]
    assert "face clearly visible" in prompt["positive"]
    assert "neutral expression" in prompt["positive"]
    assert "卡爾 reference sheet for identity" in prompt["positive"]
    assert "muted contrast" in prompt["positive"]
    assert "avoid stylized exaggeration" in prompt["positive"]
    assert "consistency notes: 臉必須一致" in prompt["positive"]
    assert "single character only" in prompt["positive"]
    assert "preserve the same character identity" in prompt["positive"]
    assert "exactly one character, one pose, one camera angle" in prompt["positive"]


def test_face_detail_prompt_locks_same_identity_and_face_details() -> None:
    prompt = build_image_prompt(_styled_manifest(), purpose="identity", angle="face_detail", multi_angle=True)
    assert prompt["angle"] == "face_detail"
    assert "extreme facial close-up" in prompt["positive"]
    assert "single character only" in prompt["positive"]
    assert "one face only, one head only" in prompt["positive"]
    assert "same character identity as the turnaround references" in prompt["positive"]
    assert "use the same person as all identity reference images" in prompt["positive"]
    assert "facial landmarks and micro details clearly readable" in prompt["positive"]
    assert "no hands covering face" in prompt["positive"]


def test_face_detail_purpose_defaults_to_face_detail_rules() -> None:
    prompt = build_image_prompt(_styled_manifest(), purpose="face_detail", multi_angle=False)
    assert prompt["angle"] == "face_detail"
    assert "extreme facial close-up" in prompt["positive"]
    assert "same character identity as the turnaround references" in prompt["positive"]
    assert "single character only" in prompt["positive"]
    assert "one face only, one head only" in prompt["positive"]


def test_angle_prompt_preserves_forward_compatible_visual_fields() -> None:
    data = _styled_manifest()
    data["_style"]["character_style"]["visual"]["custom_lens"] = "anamorphic"
    data["_style"]["character_style"]["visual"]["render_engine"] = "octane"
    prompt = build_image_prompt(data, purpose="identity", angle="three_quarter", multi_angle=True)
    assert "three-quarter view" in prompt["positive"]
    assert "custom lens: anamorphic" in prompt["positive"]
    assert "render engine: octane" in prompt["positive"]


def test_single_identity_request_defaults_to_front_angle() -> None:
    request = assemble_request(_styled_manifest(), purpose="identity", multi_angle=False)
    assert request.extra["angle"] == "front"


def test_null_provider_emits_placeholder_image_bytes() -> None:
    request = assemble_request(_styled_manifest(), purpose="identity", multi_angle=False)
    result = get_provider("null").generate(request)
    assert result.images[0].data
    assert result.images[0].mime_type == "image/png"


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
    assert payload["manifest"]["_identity"]["ref_images"][-1]["path"].startswith("assets/face_detail/")
    assert payload["manifest"]["_extensions"]["image_gen"]["provider"] == "null"
    assert len(payload["angles"]) == len(MULTI_VIEW_ANGLES) + 1
    assert "face_detail" in payload["angles"]
    assert payload["face_detail_images"]
    assert payload["face_detail_images"][0]["angle"] == "face_detail"
    assert payload["thumbnail_image"]["angle"] == "face_detail"
    assert payload["thumbnail_asset_path"].startswith("assets/face_detail/")
    assert payload["face_detail_asset_path"].startswith("assets/face_detail/")
    assert payload["face_detail_count"] >= 1
    assert payload["manifest"]["_meta"]["thumbnail"].startswith("assets/face_detail/")
    stored = service.store.read_current_manifest("character-卡爾")
    assert stored is not None
    assert stored["_extensions"]["image_gen"]["last_job_id"]
    assert stored["_extensions"]["image_gen"]["last_face_detail_paths"]


def test_face_detail_generation_uses_single_face_detail_angle(tmp_path: Path) -> None:
    service = ImagingService(store=CharpassStore(tmp_path))
    payload = service.generate_for_manifest(
        _styled_manifest(),
        purpose="face_detail",
        provider_name="null",
        persist_entity_id="character-卡爾",
    )
    assert payload["angles"] == ["face_detail"]
    assert len(payload["images"]) == 1
    assert payload["images"][0]["angle"] == "face_detail"
    assert payload["images"][0]["filename"].startswith("face_detail_")


def test_persist_downloads_remote_images_and_writes_generation_records(
    tmp_path: Path, monkeypatch
) -> None:
    from characteros.imaging.base import GeneratedImage, ImageGenResult

    class DummyResponse:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class DummyClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str) -> DummyResponse:
            assert url == "https://example.com/front.png"
            return DummyResponse(b"png-bytes")

    monkeypatch.setattr("httpx.Client", DummyClient)

    service = ImagingService(store=CharpassStore(tmp_path))
    provider = get_provider("null")
    def fake_generate(_request):
        return ImageGenResult(
            provider="wan",
            model="wan2.7-image-pro",
            images=[
                GeneratedImage(
                    filename="ref_face_front_001.png",
                    url="https://example.com/front.png",
                    mime_type="image/png",
                    metadata={"angle": "front"},
                )
            ],
            raw={"output": {"choices": [{"message": {"content": [{"image": "https://example.com/front.png"}]}}]}},
        )

    monkeypatch.setattr(provider, "generate", fake_generate)
    monkeypatch.setattr("characteros.services.imaging.get_provider", lambda *args, **kwargs: provider)

    payload = service.generate_for_manifest(
        _styled_manifest(),
        purpose="identity",
        provider_name="wan",
        persist_entity_id="character-卡爾",
        multi_angle=False,
    )

    stored = service.store.read_current_manifest("character-卡爾")
    assert stored is not None
    image_gen = stored["_extensions"]["image_gen"]
    assert image_gen["last_api_response_path"].startswith("causal/image_gen/identity/")
    assert image_gen["last_request_path"].startswith("causal/image_gen/identity/")
    assert image_gen["history"]

    entity_dir = service.store.entity_dir("character-卡爾")
    assert (entity_dir / "assets" / "identity" / "ref_face_front_001.png").read_bytes() == b"png-bytes"
    job_id = image_gen["last_job_id"]
    assert (entity_dir / "causal" / "image_gen" / "identity" / job_id / "request.json").is_file()
    assert (entity_dir / "causal" / "image_gen" / "identity" / job_id / "response.json").is_file()
    assert payload["images"][0]["url"] == "https://example.com/front.png"


def test_persist_pending_review_stages_assets_until_accept(
    tmp_path: Path, monkeypatch
) -> None:
    from characteros.imaging.base import GeneratedImage, ImageGenResult

    class DummyResponse:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class DummyClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str) -> DummyResponse:
            assert url == "https://example.com/front.png"
            return DummyResponse(b"png-bytes")

    monkeypatch.setattr("httpx.Client", DummyClient)

    service = ImagingService(store=CharpassStore(tmp_path))
    provider = get_provider("null")

    def fake_generate(_request):
        return ImageGenResult(
            provider="wan",
            model="wan2.7-image-pro",
            images=[
                GeneratedImage(
                    filename="ref_face_front_001.png",
                    url="https://example.com/front.png",
                    mime_type="image/png",
                    metadata={"angle": "front"},
                )
            ],
            raw={},
        )

    monkeypatch.setattr(provider, "generate", fake_generate)
    monkeypatch.setattr("characteros.services.imaging.get_provider", lambda *args, **kwargs: provider)

    payload = service.generate_for_manifest(
        _styled_manifest(),
        purpose="identity",
        provider_name="wan",
        persist_entity_id="character-卡爾",
        multi_angle=False,
        auto_accept=False,
    )

    image = payload["images"][0]
    assert image["asset_path"].startswith("causal/review/identity/")
    assert image["final_asset_path"].startswith("assets/identity/")
    assert payload["review"]["status"] == "pending"

    entity_dir = service.store.entity_dir("character-卡爾")
    assert (entity_dir / image["asset_path"]).is_file()
    assert not (entity_dir / image["final_asset_path"]).exists()

    promoted = finalize_reviewed_generation("character-卡爾", payload, store=service.store)
    assert promoted["payload"]["review"]["status"] == "accepted"
    assert promoted["payload"]["images"][0]["asset_path"] == image["final_asset_path"]
    assert promoted["payload"]["thumbnail_asset_path"] == image["final_asset_path"]


def test_outfit_purpose_writes_style_refs() -> None:
    request = assemble_request(_styled_manifest(), purpose="outfit")
    result = get_provider("null").generate(request)
    updated = apply_result_to_manifest(_styled_manifest(), request, result)
    refs = updated["_style"]["outfit"]["ref_images"]
    assert refs
    assert refs[-1]["path"].startswith("assets/style/")


def test_imaging_settings_reads_legacy_env(monkeypatch) -> None:
    from characteros.imaging.config_store import (
        ENV_BASE_URL,
        ENV_MODEL,
        LEGACY_ENV_BASE_URL,
        LEGACY_ENV_MODEL,
    )
    from characteros.imaging.settings import ImagingSettings

    monkeypatch.delenv(ENV_BASE_URL, raising=False)
    monkeypatch.delenv(ENV_MODEL, raising=False)
    monkeypatch.setenv(LEGACY_ENV_BASE_URL, "https://legacy.example/v1")
    monkeypatch.setenv(LEGACY_ENV_MODEL, "legacy-model")

    settings = ImagingSettings()
    assert settings.get_base_url() == "https://legacy.example/v1"
    assert settings.get_model() == "legacy-model"


def test_imaging_settings_prefers_new_env_over_legacy(monkeypatch) -> None:
    from characteros.imaging.config_store import ENV_BASE_URL, LEGACY_ENV_BASE_URL
    from characteros.imaging.settings import ImagingSettings

    monkeypatch.setenv(ENV_BASE_URL, "https://new.example/v1")
    monkeypatch.setenv(LEGACY_ENV_BASE_URL, "https://legacy.example/v1")

    settings = ImagingSettings()
    assert settings.get_base_url() == "https://new.example/v1"


def test_imaging_settings_update_falls_back_to_env_when_db_fails(monkeypatch) -> None:
    from sqlalchemy.exc import OperationalError

    from characteros.imaging.config_store import ENV_BASE_URL
    from characteros.imaging.settings import ImagingSettings

    class BrokenSession:
        pass

    settings = ImagingSettings()

    def boom(*_args, **_kwargs):
        raise OperationalError("stmt", {}, Exception("connection refused"))

    monkeypatch.setattr(
        "characteros.imaging.settings.save_values",
        boom,
    )

    snap = settings.update(
        BrokenSession(),
        base_url="https://env-only.example/v1",
        persist_env=False,
    )
    assert snap.base_url == "https://env-only.example/v1"
    assert settings.get_base_url() == "https://env-only.example/v1"
    assert os.environ.get(ENV_BASE_URL) == "https://env-only.example/v1"


def test_load_from_db_swallows_db_errors() -> None:
    from sqlalchemy.exc import OperationalError

    from characteros.imaging.settings import ImagingSettings

    class BrokenSession:
        def get(self, *_args, **_kwargs):
            raise OperationalError("stmt", {}, Exception("connection refused"))

    settings = ImagingSettings()
    settings.load_from_db(BrokenSession())  # should not raise


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

