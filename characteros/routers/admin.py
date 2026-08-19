"""CharacterOS 管理路由：佇列統計與系統指標。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from characteros.models.database import get_db
from characteros.models.schema import QueueStatsResponse, SystemMetricsResponse
from characteros.services.queue import QueueManager

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


@router.get("/queue-stats", response_model=QueueStatsResponse)
def get_queue_stats(db: Session = Depends(get_db)):
    """
    取得佇列統計資訊（管理用）
    
    包含：
    - 各狀態變體數量（pending, ready, failed）
    - 平均等待時間
    - 最老 pending 記錄的年齡
    """
    queue_mgr = QueueManager(db)
    stats = queue_mgr.get_queue_stats()
    return QueueStatsResponse(**stats)


@router.get("/metrics", response_model=SystemMetricsResponse)
def get_system_metrics(db: Session = Depends(get_db)):
    """
    取得系統效能指標（管理用）
    
    包含：
    - 資料庫連線數
    - 快取命中率（若使用 Redis）
    - API 回應時間 P95
    - 總角色數、Profile 數、變體數
    """
    from characteros.models.orm import CharacterCore, CharacterProfile, CharacterVariant
    from sqlalchemy import func
    
    # 計算總數
    total_characters = db.query(func.count(CharacterCore.id)).scalar() or 0
    total_profiles = db.query(func.count(CharacterProfile.id)).scalar() or 0
    total_variants = db.query(func.count(CharacterVariant.id)).scalar() or 0
    
    # 資料庫連線數（從 engine 取得）
    from characteros.models.database import engine
    pool_status = engine.pool.status()
    
    # 注意：實際的 cache_hit_rate 和 p95 需要整合 Redis 與監控系統
    # 此處先回傳預設值
    return SystemMetricsResponse(
        database_connections=1,  # 簡化表示
        cache_hit_rate=0.0,  # 待整合 Redis
        api_response_time_p95_ms=0.0,  # 待整合監控
        total_characters=total_characters,
        total_profiles=total_profiles,
        total_variants=total_variants
    )
