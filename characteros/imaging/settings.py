"""生圖設定中心：統一管理 provider / endpoint / model / api key。"""



from __future__ import annotations



import os

from dataclasses import dataclass

from threading import Lock



from sqlalchemy.orm import Session



from characteros.imaging.config_store import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    ENV_API_KEY,
    ENV_BASE_URL,
    ENV_MODEL,
    ENV_PROVIDER,
    ImagingConfigValues,
    apply_to_environ,
    load_values,
    save_values,
)





@dataclass

class ImagingConfigSnapshot:

    provider: str

    base_url: str

    model: str

    has_api_key: bool





class ImagingSettings:

    """優先序：記憶體快取 → DB（啟動載入）→ 環境變數 → 預設值。"""



    def __init__(self) -> None:

        self._lock = Lock()

        self._cached: ImagingConfigValues | None = None



    def load_from_db(self, db: Session) -> None:

        """啟動時從 DB 載入；無列時保留 .env 現值。"""

        values = load_values(db)

        if values is None:

            return

        with self._lock:

            self._cached = values

        apply_to_environ(values)



    def _resolve(self) -> ImagingConfigValues:

        with self._lock:

            if self._cached is not None:

                return self._cached

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



    def get_provider(self) -> str:

        return self._resolve().provider



    def get_base_url(self) -> str:

        return self._resolve().base_url



    def get_model(self) -> str:

        return self._resolve().model



    def get_api_key(self) -> str:

        return self._resolve().api_key



    def snapshot(self) -> ImagingConfigSnapshot:

        values = self._resolve()

        return ImagingConfigSnapshot(

            provider=values.provider,

            base_url=values.base_url,

            model=values.model,

            has_api_key=bool(values.api_key),

        )



    def update(

        self,

        db: Session,

        *,

        provider: str | None = None,

        base_url: str | None = None,

        model: str | None = None,

        api_key: str | None = None,

        clear_api_key: bool = False,

        persist_env: bool = True,

    ) -> ImagingConfigSnapshot:

        values = save_values(

            db,

            provider=provider,

            base_url=base_url,

            model=model,

            api_key=api_key,

            clear_api_key=clear_api_key,

            persist_env=persist_env,

        )

        with self._lock:

            self._cached = values

        return self.snapshot()





settings = ImagingSettings()

