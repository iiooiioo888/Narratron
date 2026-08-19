"""API 閘道 FastAPI。"""

from narratron.api.app import app
from narratron.api.settings import Settings, get_settings

__all__ = ["Settings", "app", "get_settings"]
