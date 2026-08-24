"""CharacterOS 健康檢查路由。"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from characteros.models.database import get_db
from characteros.models.schema import HealthCheckResponse
from characteros.storage.db_availability import mark_database_unavailable, storage_mode_label

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthCheckResponse)
@router.get("/api/v1/health", response_model=HealthCheckResponse)
def health_check(db: Session = Depends(get_db)):
    """
    健康檢查端點
    
    檢查項目：
    - 資料庫連線狀態
    - 基本服務可用性
    
    回應狀態：
    - `healthy`: 所有服務正常
    - `degraded`: 部分服務異常但不影響核心功能
    - `unhealthy`: 嚴重錯誤，無法提供服務
    """
    try:
        db.execute(text("SELECT 1"))
        return HealthCheckResponse(
            status="healthy",
            database="connected",
            timestamp=datetime.now(timezone.utc),
            storage_mode=storage_mode_label(),
        )
    except SQLAlchemyError:
        mark_database_unavailable()
        return HealthCheckResponse(
            status="degraded",
            database="disconnected",
            timestamp=datetime.now(timezone.utc),
            storage_mode=storage_mode_label(),
        )
