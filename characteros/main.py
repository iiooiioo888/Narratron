"""CharacterOS FastAPI 入口：角色資產唯讀查詢與變體佇列。"""
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from sqlalchemy.exc import OperationalError

from characteros.models.database import engine, Base
from characteros.routers import characters, admin, health, imaging, panel

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

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
    openapi_url="/openapi.json"
)

# CORS 設定（開發階段允許所有來源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生產環境應限制為特定網域
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


@app.on_event("startup")
async def startup_event():
    """
    應用程式啟動時執行
    """
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
    
    # 注意：資料庫表應透過 migration 腳本創建
    # 此處僅做驗證，不自動創建表
    logger.info("Database connection configured (use migrations to create tables)")
    
    from characteros.services.queue_worker import start_queue_worker, wake_queue_worker

    start_queue_worker()
    wake_queue_worker()
    logger.info("Startup complete!")


@app.on_event("shutdown")
async def shutdown_event():
    """
    應用程式關閉時執行
    """
    logger.info("Shutting down CharacterOS...")


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


# 全域例外處理（可選）
@app.exception_handler(OperationalError)
async def database_unavailable_handler(request, exc):
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
async def global_exception_handler(request, exc):
    """
    全域例外處理器（必須回傳 JSONResponse，否則 Starlette 會再拋 500 純文字）
    """
    logger.error(f"Unhandled exception: {exc}", exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "type": type(exc).__name__,
        },
    )
