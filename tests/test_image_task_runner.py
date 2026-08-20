"""image_task_runner 共用生圖邏輯測試。"""

from __future__ import annotations

from characteros.services.image_task_runner import resolve_imaging_credentials


def test_resolve_imaging_credentials_prefers_task_overrides() -> None:
    creds = resolve_imaging_credentials(
        {
            "provider": "wan",
            "model": "task-model",
            "base_url": "https://example.test/v1",
            "api_key": "task-key",
        }
    )
    assert creds.provider_name == "wan"
    assert creds.model == "task-model"
    assert creds.base_url == "https://example.test/v1"
    assert creds.api_key == "task-key"


def test_resolve_imaging_credentials_null_provider_skips_defaults() -> None:
    creds = resolve_imaging_credentials({"provider": "null"})
    assert creds.provider_name == "null"
    assert creds.model == ""
    assert creds.base_url == ""
    assert creds.api_key == ""
