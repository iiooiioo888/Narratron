"""API 閘道 FastAPI 入口。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from narratron.api.routes import router
from narratron.api.settings import get_settings
from narratron.naming import PLATFORM

app = FastAPI(
    title=f"{PLATFORM} API Gateway",
    version="2.0.0",
    description="Alpha Q1 閘道。/parse 與 /direct 已通；Keeper / Runner / Muxer 仍回 501。",
)

_CORS_ORIGINS = [
    "http://localhost:8001",
    "http://127.0.0.1:8001",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8501",
    "http://127.0.0.1:8501",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/", include_in_schema=False)
async def root_redirect():
    """根路徑轉址到 CharacterOS 門面首頁。"""
    settings = get_settings()
    panel_url = settings.characteros_panel_url
    # 導向 CharacterOS 的首頁（landing page）
    home_url = panel_url.rsplit("/admin/panel", 1)[0] + "/"
    return RedirectResponse(url=home_url, status_code=307)
