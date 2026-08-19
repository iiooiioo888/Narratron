"""生圖設定持久化：資料庫 + .env 雙寫。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from characteros.models.orm import ImagingConfig
from characteros.utils.env_file import upsert_env_vars

ENV_PROVIDER = "CHARACTEROS_IMAGE_GEN_PROVIDER"
ENV_BASE_URL = "CHARACTEROS_OPENAI_IMAGES_BASE_URL"
ENV_MODEL = "CHARACTEROS_OPENAI_IMAGES_MODEL"
ENV_API_KEY = "CHARACTEROS_IMAGE_GEN_API_KEY"

DEFAULT_PROVIDER = "null"
DEFAULT_BASE_URL = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "wan2.7-image-pro"

SINGLETON_ID = 1


@dataclass
class ImagingConfigValues:
    provider: str
    base_url: str
    model: str
    api_key: str


def _defaults_from_env() -> ImagingConfigValues:
    return ImagingConfigValues(
        provider=(os.environ.get(ENV_PROVIDER) or DEFAULT_PROVIDER).strip().lower(),
        base_url=(os.environ.get(ENV_BASE_URL) or DEFAULT_BASE_URL).rstrip("/"),
        model=(os.environ.get(ENV_MODEL) or DEFAULT_MODEL).strip(),
        api_key=(
            os.environ.get(ENV_API_KEY)
            or os.environ.get("OPENAI_API_KEY")
            or ""
        ).strip(),
    )


def _get_or_create_row(db: Session) -> ImagingConfig:
    row = db.get(ImagingConfig, SINGLETON_ID)
    if row is None:
        defaults = _defaults_from_env()
        row = ImagingConfig(
            id=SINGLETON_ID,
            provider=defaults.provider,
            base_url=defaults.base_url,
            model=defaults.model,
            api_key=defaults.api_key or None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def load_values(db: Session) -> ImagingConfigValues | None:
    """從 DB 讀取；無資料列時回傳 None（呼叫端回退 env）。"""
    row = db.get(ImagingConfig, SINGLETON_ID)
    if row is None:
        return None
    return ImagingConfigValues(
        provider=(row.provider or DEFAULT_PROVIDER).strip().lower(),
        base_url=(row.base_url or DEFAULT_BASE_URL).rstrip("/"),
        model=(row.model or DEFAULT_MODEL).strip(),
        api_key=(row.api_key or "").strip(),
    )


def save_values(
    db: Session,
    *,
    provider: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    clear_api_key: bool = False,
    persist_env: bool = True,
    env_path: Path | None = None,
) -> ImagingConfigValues:
    """寫入 DB，並可選同步 .env 與 os.environ。"""
    row = _get_or_create_row(db)
    env_updates: dict[str, str | None] = {}

    if provider is not None:
        cleaned = provider.strip().lower() or DEFAULT_PROVIDER
        row.provider = cleaned
        env_updates[ENV_PROVIDER] = cleaned
    if base_url is not None:
        cleaned = base_url.strip().rstrip("/") or DEFAULT_BASE_URL
        row.base_url = cleaned
        env_updates[ENV_BASE_URL] = cleaned
    if model is not None:
        cleaned = model.strip() or DEFAULT_MODEL
        row.model = cleaned
        env_updates[ENV_MODEL] = cleaned
    if clear_api_key:
        row.api_key = None
        env_updates[ENV_API_KEY] = None
    elif api_key is not None:
        cleaned = api_key.strip()
        row.api_key = cleaned or None
        env_updates[ENV_API_KEY] = cleaned or None

    db.commit()
    db.refresh(row)

    values = ImagingConfigValues(
        provider=(row.provider or DEFAULT_PROVIDER).strip().lower(),
        base_url=(row.base_url or DEFAULT_BASE_URL).rstrip("/"),
        model=(row.model or DEFAULT_MODEL).strip(),
        api_key=(row.api_key or "").strip(),
    )

    if persist_env and env_updates:
        upsert_env_vars(env_updates, env_path=env_path)

    _apply_to_environ(values, keys=set(env_updates.keys()) if env_updates else None)
    return values


def apply_to_environ(values: ImagingConfigValues, keys: set[str] | None = None) -> None:
    """將設定套用到程序內 os.environ。"""
    mapping = {
        ENV_PROVIDER: values.provider,
        ENV_BASE_URL: values.base_url,
        ENV_MODEL: values.model,
        ENV_API_KEY: values.api_key or None,
    }
    for key, value in mapping.items():
        if keys is not None and key not in keys:
            continue
        if value is None or value == "":
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
