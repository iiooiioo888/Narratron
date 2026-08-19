"""生圖設定中心：統一管理 provider / endpoint / model / api key。"""



from __future__ import annotations



from dataclasses import dataclass

from threading import Lock



from sqlalchemy.exc import SQLAlchemyError

from sqlalchemy.orm import Session



from characteros.imaging.config_store import (
    ImagingConfigValues,
    _defaults_from_env,
    apply_to_environ,
    load_values,
    save_values,
    save_values_env_only,
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

        """啟動時從 DB 載入；無列或連線失敗時保留 .env 現值。"""

        try:

            values = load_values(db)

        except SQLAlchemyError:

            return

        if values is None:

            return

        with self._lock:

            self._cached = values

        apply_to_environ(values)



    def _resolve(self) -> ImagingConfigValues:

        with self._lock:

            if self._cached is not None:

                return self._cached

        # 與 config_store._defaults_from_env 一致，含舊版 CHARACTEROS_OPENAI_IMAGES_* 回退。
        return _defaults_from_env()



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



    def update_env_only(
        self,
        *,
        provider: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        clear_api_key: bool = False,
        persist_env: bool = True,
    ) -> ImagingConfigSnapshot:
        """PostgreSQL 不可用時：僅更新記憶體與 .env。"""
        values = save_values_env_only(
            provider=provider,
            base_url=base_url,
            model=model,
            api_key=api_key,
            clear_api_key=clear_api_key,
            persist_env=persist_env,
            base=self._resolve(),
        )
        with self._lock:
            self._cached = values
        return self.snapshot()

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

        try:

            values = save_values(

                db,

                provider=provider,

                base_url=base_url,

                model=model,

                api_key=api_key,

                clear_api_key=clear_api_key,

                persist_env=persist_env,

            )

        except SQLAlchemyError:

            values = save_values_env_only(

                provider=provider,

                base_url=base_url,

                model=model,

                api_key=api_key,

                clear_api_key=clear_api_key,

                persist_env=persist_env,

                base=self._resolve(),

            )

        with self._lock:

            self._cached = values

        return self.snapshot()





settings = ImagingSettings()

