"""生圖設定持久化：資料庫 + .env 雙寫。"""



from __future__ import annotations



import os

from dataclasses import dataclass

from pathlib import Path



from sqlalchemy.orm import Session



from characteros.models.orm import ImagingConfig

from characteros.utils.env_file import upsert_env_vars



ENV_PROVIDER = "CHARACTEROS_IMAGE_GEN_PROVIDER"
ENV_BASE_URL = "CHARACTEROS_IMAGE_GEN_BASE_URL"
ENV_MODEL = "CHARACTEROS_IMAGE_GEN_MODEL"
ENV_API_KEY = "CHARACTEROS_IMAGE_GEN_API_KEY"

# 向後相容：早期變數命名帶有 OPENAI 字樣，仍可讀寫。
LEGACY_ENV_BASE_URL = "CHARACTEROS_OPENAI_IMAGES_BASE_URL"
LEGACY_ENV_MODEL = "CHARACTEROS_OPENAI_IMAGES_MODEL"



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

        base_url=(
            os.environ.get(ENV_BASE_URL)
            or os.environ.get(LEGACY_ENV_BASE_URL)
            or DEFAULT_BASE_URL
        ).rstrip("/"),

        model=(
            os.environ.get(ENV_MODEL)
            or os.environ.get(LEGACY_ENV_MODEL)
            or DEFAULT_MODEL
        ).strip(),

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





def _merge_updates(

    current: ImagingConfigValues,

    *,

    provider: str | None = None,

    base_url: str | None = None,

    model: str | None = None,

    api_key: str | None = None,

    clear_api_key: bool = False,

) -> tuple[ImagingConfigValues, dict[str, str | None]]:

    """合併局部更新，回傳新值與需寫入 .env 的鍵。"""

    env_updates: dict[str, str | None] = {}

    next_provider = current.provider

    next_base_url = current.base_url

    next_model = current.model

    next_api_key = current.api_key



    if provider is not None:

        next_provider = provider.strip().lower() or DEFAULT_PROVIDER

        env_updates[ENV_PROVIDER] = next_provider

    if base_url is not None:

        next_base_url = base_url.strip().rstrip("/") or DEFAULT_BASE_URL

        env_updates[ENV_BASE_URL] = next_base_url

        env_updates[LEGACY_ENV_BASE_URL] = next_base_url

    if model is not None:

        next_model = model.strip() or DEFAULT_MODEL

        env_updates[ENV_MODEL] = next_model

        env_updates[LEGACY_ENV_MODEL] = next_model

    if clear_api_key:

        next_api_key = ""

        env_updates[ENV_API_KEY] = None

    elif api_key is not None:

        next_api_key = api_key.strip()

        env_updates[ENV_API_KEY] = next_api_key or None



    return (

        ImagingConfigValues(

            provider=next_provider,

            base_url=next_base_url,

            model=next_model,

            api_key=next_api_key,

        ),

        env_updates,

    )





def save_values_env_only(

    *,

    provider: str | None = None,

    base_url: str | None = None,

    model: str | None = None,

    api_key: str | None = None,

    clear_api_key: bool = False,

    persist_env: bool = True,

    env_path: Path | None = None,

    base: ImagingConfigValues | None = None,

) -> ImagingConfigValues:

    """DB 不可用時：僅更新記憶體／.env（含舊版 LEGACY 鍵）。"""

    values, env_updates = _merge_updates(

        base or _defaults_from_env(),

        provider=provider,

        base_url=base_url,

        model=model,

        api_key=api_key,

        clear_api_key=clear_api_key,

    )

    if persist_env and env_updates:

        upsert_env_vars(env_updates, env_path=env_path)

    apply_to_environ(values, keys=set(env_updates.keys()) if env_updates else None)

    return values





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

    current = ImagingConfigValues(

        provider=(row.provider or DEFAULT_PROVIDER).strip().lower(),

        base_url=(row.base_url or DEFAULT_BASE_URL).rstrip("/"),

        model=(row.model or DEFAULT_MODEL).strip(),

        api_key=(row.api_key or "").strip(),

    )

    values, env_updates = _merge_updates(

        current,

        provider=provider,

        base_url=base_url,

        model=model,

        api_key=api_key,

        clear_api_key=clear_api_key,

    )

    row.provider = values.provider

    row.base_url = values.base_url

    row.model = values.model

    row.api_key = values.api_key or None



    db.commit()

    db.refresh(row)



    if persist_env and env_updates:

        upsert_env_vars(env_updates, env_path=env_path)



    apply_to_environ(values, keys=set(env_updates.keys()) if env_updates else None)

    return values





def apply_to_environ(values: ImagingConfigValues, keys: set[str] | None = None) -> None:

    """將設定套用到程序內 os.environ。"""

    mapping = {

        ENV_PROVIDER: values.provider,

        ENV_BASE_URL: values.base_url,
        LEGACY_ENV_BASE_URL: values.base_url,

        ENV_MODEL: values.model,
        LEGACY_ENV_MODEL: values.model,

        ENV_API_KEY: values.api_key or None,

    }

    for key, value in mapping.items():

        if keys is not None and key not in keys:

            continue

        if value is None or value == "":

            os.environ.pop(key, None)

        else:

            os.environ[key] = value

