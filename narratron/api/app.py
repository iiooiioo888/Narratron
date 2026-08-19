"""API 閘道 FastAPI 入口。"""

from __future__ import annotations

from fastapi import FastAPI

from narratron.api.routes import router
from narratron.naming import PLATFORM

app = FastAPI(
    title=f"{PLATFORM} API Gateway",
    version="2.0.0",
    description="Alpha Q1 閘道。/parse 與 /direct 已通；Keeper / Runner / Muxer 仍回 501。",
)
app.include_router(router)
