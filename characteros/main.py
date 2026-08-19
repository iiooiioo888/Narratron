"""CharacterOS FastAPI 入口：角色資產唯讀查詢與變體佇列。"""

from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from characteros.models.database import engine, Base
from characteros.routers import characters, admin, health, imaging, panel

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理（取代棄用的 on_event）。"""
    logger.info("Starting up CharacterOS...")

    from characteros.imaging.settings import settings
    from characteros.models.database import SessionLocal

    db = SessionLocal()
    try:
        settings.load_from_db(db)
        logger.info("Imaging config loaded from database (fallback: .env)")
    except Exception as exc:
        logger.warning("Could not load imaging config from database: %s", exc)
    finally:
        db.close()

    logger.info("Database connection configured (use migrations to create tables)")
    logger.info("Startup complete!")

    yield

    logger.info("Shutting down CharacterOS...")


# 建立 FastAPI 應用
app = FastAPI(
    title="CharacterOS",
    description="""
## CharacterOS（角色控制子系統）

**One ID, Infinite Evolutions.**

一個「唯讀、可演化、高擴展」的 AI 角色資產管理後端。

### 核心功能

- **角色查詢**: 取得完整 `.charpass` 格式的角色檔案
- **變體請求**: 請求角色的進化外觀（年齡、情緒、傷痕等）
- **第三方生圖**: 依 `_style.character_style` 組 prompt，呼叫可插拔 provider
- **佇列管理**: 背景非同步生成變體
- **管理儀表板**: 監控佇列狀態與系統指標

### 設計原則

- **唯讀 API**: 所有寫入由離線管理工具執行
- **不存在即 404**: 查詢不存在的角色直接回傳錯誤
- **變體首次請求即 202**: 未生成的變體自動排入佇列
- **三層儲存**: Core → Profile → Variant，各自獨立演化
    """,
    version="1.0.0-sprint1",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS 設定
import os
_cors_origins = os.environ.get("CHARACTEROS_CORS_ORIGINS", "").strip()
_allowed_origins = [o.strip() for o in _cors_origins.split(",") if o.strip()] if _cors_origins else ["http://localhost:3000", "http://localhost:8001"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 註冊路由
app.include_router(characters.router)
app.include_router(imaging.router)
app.include_router(admin.router)
app.include_router(health.router)
app.include_router(panel.router)


@app.get("/")
async def root():
    """
    根路徑：返回 API 基本資訊
    """
    return {
        "name": "CharacterOS",
        "version": "1.0.0-sprint1",
        "description": "角色控制子系統",
        "docs": "/docs",
        "health": "/health"
    }


# 全域例外處理
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全域例外處理器：回傳 500 而非洩漏內部實作細節。"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
