"""
Narratron CharacterOS - Queue Manager
負責變體佇列的管理：檢查、寫入、冪等性保護
Sprint 1 僅負責寫入 pending 狀態，不執行實際生成
"""

from typing import Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import logging

from app.models.orm import CharacterCore, CharacterProfile, CharacterVariant
from app.utils.hash_utils import compute_variant_hash

logger = logging.getLogger(__name__)


class QueueManager:
    """
    佇列管理器：處理變體生成請求的冪等性與佇列寫入
    
    核心邏輯：
    1. 計算 variant_hash
    2. 檢查是否已存在（無論 status）
    3. 若存在且 ready → 直接回傳
    4. 若存在且 pending → 回傳現有 queue_id（避免重複）
    5. 若不存在 → 寫入新記錄（status='pending'）
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def request_variant_generation(
        self,
        core_id: int,
        evolution_params: Dict[str, Any],
        priority: int = 0
    ) -> Tuple[CharacterVariant, bool]:
        """
        請求變體生成
        
        Args:
            core_id: 角色核心 ID
            evolution_params: 演化參數
            priority: 優先級 (0-10)
        
        Returns:
            Tuple[CharacterVariant, is_new]
            - CharacterVariant: 變體記錄（現有的或新建的）
            - is_new: True 如果是新建的，False 如果是現有的
        
        Raises:
            HTTPException 404 if core not found
        """
        # 1. 驗證 core 存在
        core = self.db.query(CharacterCore).filter(CharacterCore.id == core_id).first()
        if not core:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character core {core_id} not found"
            )
        
        # 2. 取得 active profile 的版本號（用於 hash 計算）
        active_profile = self.db.query(CharacterProfile).filter(
            CharacterProfile.core_id == core_id,
            CharacterProfile.is_active == True
        ).order_by(CharacterProfile.version.desc()).first()
        
        profile_version = active_profile.version if active_profile else 1
        profile_id = active_profile.id if active_profile else None
        
        # 3. 計算 variant_hash
        variant_hash = compute_variant_hash(core_id, profile_version, evolution_params)
        
        # 4. 檢查是否已存在
        existing_variant = self.db.query(CharacterVariant).filter(
            CharacterVariant.core_id == core_id,
            CharacterVariant.variant_hash == variant_hash
        ).first()
        
        if existing_variant:
            # 已存在，直接回傳（無論 status 是 pending/ready/failed）
            logger.info(
                f"Variant already exists: core_id={core_id}, hash={variant_hash[:16]}..., "
                f"status={existing_variant.status}"
            )
            return existing_variant, False
        
        # 5. 不存在，創建新記錄（status='pending'）
        new_variant = CharacterVariant(
            core_id=core_id,
            profile_id=profile_id,
            variant_hash=variant_hash,
            evolution_params=evolution_params,
            status='pending',
            priority=priority,
            retry_count=0,
            max_retries=3
        )
        
        try:
            self.db.add(new_variant)
            self.db.commit()
            self.db.refresh(new_variant)
            
            logger.info(
                f"New variant queued: id={new_variant.id}, "
                f"core_id={core_id}, hash={variant_hash[:16]}..."
            )
            
            return new_variant, True
            
        except IntegrityError as e:
            # 競爭條件：另一個請求同時寫入了相同的 hash
            # 回滾並重新查詢
            self.db.rollback()
            logger.warning(f"IntegrityError on variant insert, re-querying: {e}")
            
            existing_variant = self.db.query(CharacterVariant).filter(
                CharacterVariant.core_id == core_id,
                CharacterVariant.variant_hash == variant_hash
            ).first()
            
            if existing_variant:
                return existing_variant, False
            else:
                # 極端情況：仍然找不到，可能是其他錯誤
                raise
    
    def get_variant_by_id(self, variant_id: int) -> Optional[CharacterVariant]:
        """
        透過 ID 取得變體記錄
        
        Args:
            variant_id: 變體 ID
        
        Returns:
            CharacterVariant or None
        """
        return self.db.query(CharacterVariant).filter(
            CharacterVariant.id == variant_id
        ).first()
    
    def get_pending_queue_count(self) -> int:
        """
        取得待處理佇列數量
        
        Returns:
            int: pending 狀態的變體數量
        """
        return self.db.query(CharacterVariant).filter(
            CharacterVariant.status == 'pending'
        ).count()
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """
        取得佇列統計資訊
        
        Returns:
            Dict with stats
        """
        from sqlalchemy import func
        
        # 各狀態數量
        pending_count = self.db.query(CharacterVariant).filter(
            CharacterVariant.status == 'pending'
        ).count()
        
        ready_count = self.db.query(CharacterVariant).filter(
            CharacterVariant.status == 'ready'
        ).count()
        
        failed_count = self.db.query(CharacterVariant).filter(
            CharacterVariant.status == 'failed'
        ).count()
        
        # 平均等待時間（僅計算有 queue_wait_ms 的記錄）
        avg_wait = self.db.query(func.avg(CharacterVariant.queue_wait_ms)).filter(
            CharacterVariant.queue_wait_ms != None
        ).scalar() or 0.0
        
        # 最老的 pending 記錄
        oldest_pending = self.db.query(CharacterVariant).filter(
            CharacterVariant.status == 'pending'
        ).order_by(CharacterVariant.created_at.asc()).first()
        
        oldest_age_seconds = 0.0
        if oldest_pending:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            created = oldest_pending.created_at.replace(tzinfo=timezone.utc)
            oldest_age_seconds = (now - created).total_seconds()
        
        return {
            "total_pending": pending_count,
            "total_ready": ready_count,
            "total_failed": failed_count,
            "average_wait_time_ms": float(avg_wait),
            "oldest_pending_age_seconds": oldest_age_seconds
        }
