"""環境變數契約（對應 .env.example）。不含密鑰實值預設。"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    vault_backend: str = "memory"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "narratron_vault"
    postgres_user: str = "narratron"
    postgres_password: str = "narratron"
    database_url: str = "postgresql://narratron:narratron@localhost:5432/narratron_vault"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_url: str = "redis://localhost:6379/0"

    chroma_host: str = "localhost"
    chroma_port: int = 8000
    chroma_url: str = "http://localhost:8000"

    narratron_api_host: str = "0.0.0.0"
    narratron_api_port: int = 8080
    characteros_panel_url: str = "http://localhost:8001/admin/panel"
    charpass_store_dir: str = "data/charpasses"


def get_settings() -> Settings:
    return Settings()
