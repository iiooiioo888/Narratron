"""CharacterOS 健康檢查路由。"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from characteros.models.database import get_db
from characteros.models.schema import HealthCheckResponse
from characteros.storage.db_availability import mark_database_unavailable

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthCheckResponse)
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
    db_status = "disconnected"
    
    try:
        # 測試資料庫連線
        db.execute(text("SELECT 1"))
        db_status = "connected"

        return HealthCheckResponse(
            status="healthy",
            database=db_status,
            timestamp=datetime.now(timezone.utc)
        )

    except Exception:
        mark_database_unavailable()
        return HealthCheckResponse(
            status="degraded",
            database="disconnected",
            timestamp=datetime.now(timezone.utc),
        )
