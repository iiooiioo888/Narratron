"""CharacterOS FastAPI 入口：角色資產唯讀查詢與變體佇列。"""
from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import logging
import os
from pathlib import Path

from sqlalchemy.exc import OperationalError

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
    from characteros.storage.db_availability import check_database_available, storage_mode_label

    db = SessionLocal()
    try:
        if check_database_available():
            settings.load_from_db(db)
            logger.info("Imaging config loaded from database (fallback: .env)")
        else:
            logger.warning(
                "PostgreSQL unavailable — using local charpass storage and .env for imaging config"
            )
    except Exception as exc:
        logger.warning("Could not load imaging config from database: %s", exc)
    finally:
        db.close()

    logger.info("Storage mode: %s", storage_mode_label())
    logger.info("Database connection configured (use migrations to create tables)")

    from characteros.services.queue_worker import start_queue_worker, wake_queue_worker

    start_queue_worker()
    wake_queue_worker()
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
# 開發階段可設定 CHARACTEROS_CORS_ALLOW_ALL=1 允許所有來源
# 生產環境請設定 CHARACTEROS_CORS_ORIGINS=https://your-domain.com

_cors_allow_all = os.environ.get("CHARACTEROS_CORS_ALLOW_ALL", "0") == "1"
_cors_origins_env = os.environ.get("CHARACTEROS_CORS_ORIGINS", "")
if _cors_allow_all:
    _cors_origins = ["*"]
    _cors_credentials = False
    logger.warning(
        "CHARACTEROS_CORS_ALLOW_ALL=1：CORS 允許所有來源，已關閉 credentials，"
        "避免與 allow_origins=['*'] 同時使用"
    )
else:
    _cors_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()] or [
        "http://localhost:8001",
        "http://localhost:8080",
        "http://127.0.0.1:8001",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8501",
        "http://127.0.0.1:8501",
    ]
    _cors_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 註冊路由
app.include_router(characters.router)
app.include_router(imaging.router)
app.include_router(admin.router)
app.include_router(health.router)
app.include_router(panel.router)

# 靜態檔案（CSS/JS/圖片等）
_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def root():
    """門面首頁：Narratron 專案介紹與功能入口。"""
    html_path = Path(__file__).parent / "static" / "index.html"
    if html_path.is_file():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    # fallback：若靜態檔不存在，回傳 API 資訊
    return HTMLResponse(
        content="<h1>Narratron</h1><p>static/index.html not found. Visit <a href='/docs'>/docs</a> for API.</p>"
    )


@app.get("/api-info")
async def api_info():
    """API 基本資訊（原根路徑）。"""
    return {
        "name": "CharacterOS",
        "version": "1.0.0-sprint1",
        "description": "角色控制子系統",
        "docs": "/docs",
        "health": "/health",
        "panel": "/admin/panel",
        "home": "/",
    }


# 全域例外處理
@app.exception_handler(OperationalError)
async def database_unavailable_handler(request: Request, exc: OperationalError):
    """PostgreSQL 未啟動或連線字串錯誤時回傳可解析 JSON。"""
    logger.error("Database unavailable: %s", exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "資料庫連線失敗，請確認 PostgreSQL 已啟動，"
                "且 CHARACTEROS_DATABASE_URL 設定正確"
            ),
            "type": type(exc).__name__,
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全域例外處理器：回傳 500 而非洩漏內部實作細節。"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
