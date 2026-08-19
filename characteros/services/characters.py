"""CharacterOS 角色查詢服務。"""

from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, status

from characteros.models.orm import CharacterCore, CharacterProfile, CharacterVariant
from characteros.models.schema import (
    CharacterCoreResponse,
    CharacterFullResponse,
    CharacterProfileResponse,
    CharacterVariantResponse,
)


class CharacterService:
    """
    角色服務：提供唯讀查詢功能
    遵循「不存在即 404」原則
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_character_by_id(self, character_id: int) -> CharacterFullResponse:
        """
        取得角色完整資訊（Core + Active Profile）
        
        Args:
            character_id: 角色核心 ID
        
        Returns:
            CharacterFullResponse
        
        Raises:
            HTTPException 404 if not found
        """
        # 查詢 Core，並預載入 active profile
        core = self.db.query(CharacterCore).options(
            joinedload(CharacterCore.profiles).and_(CharacterProfile.is_active == True)
        ).filter(CharacterCore.id == character_id).first()
        
        if not core:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character with id {character_id} not found"
            )
        
        # 取得 active profile（可能有多個版本，只取最新啟用的）
        active_profile = None
        if core.profiles:
            # 按版本號降序排列，取第一個
            active_profile = sorted(
                [p for p in core.profiles if p.is_active],
                key=lambda x: x.version,
                reverse=True
            )[0] if any(p.is_active for p in core.profiles) else None
        
        # 查詢已生成的變體（status='ready'）
        ready_variants = self.db.query(CharacterVariant).filter(
            CharacterVariant.core_id == character_id,
            CharacterVariant.status == 'ready'
        ).limit(50).all()
        
        return CharacterFullResponse(
            core=CharacterCoreResponse.model_validate(core),
            profile=CharacterProfileResponse.model_validate(active_profile) if active_profile else None,
            available_variants=[CharacterVariantResponse.model_validate(v) for v in ready_variants]
        )
    
    def get_character_by_uuid(self, uuid: str) -> CharacterFullResponse:
        """
        透過 UUID 取得角色完整資訊
        
        Args:
            uuid: 角色 UUID 字串
        
        Returns:
            CharacterFullResponse
        
        Raises:
            HTTPException 404 if not found
        """
        core = self.db.query(CharacterCore).options(
            joinedload(CharacterCore.profiles).and_(CharacterProfile.is_active == True)
        ).filter(CharacterCore.uuid == uuid).first()
        
        if not core:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character with uuid {uuid} not found"
            )
        
        # 重用 get_character_by_id 的邏輯
        return self.get_character_by_id(core.id)
    
    def list_characters(
        self,
        skip: int = 0,
        limit: int = 20,
        name_filter: Optional[str] = None,
        tags_filter: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        列出角色（摘要資訊，支援分頁與過濾）
        
        Args:
            skip: 跳過數量（分頁）
            limit: 返回數量上限
            name_filter: 名稱模糊搜尋
            tags_filter: 標籤過濾（包含任一標籤即可）
        
        Returns:
            Dict with 'items', 'total', 'skip', 'limit'
        """
        query = self.db.query(CharacterCore)
        
        # 套用過濾條件
        if name_filter:
            query = query.filter(CharacterCore.name.ilike(f"%{name_filter}%"))
        
        if tags_filter:
            # PostgreSQL ARRAY 重疊運算子
            query = query.filter(CharacterCore.tags.overlap(tags_filter))
        
        # 計算總數
        total = query.count()
        
        # 分頁
        items = query.order_by(CharacterCore.created_at.desc()).offset(skip).limit(limit).all()
        
        return {
            "items": [CharacterCoreResponse.model_validate(item) for item in items],
            "total": total,
            "skip": skip,
            "limit": limit
        }
    
    def get_active_profile(self, core_id: int) -> Optional[CharacterProfile]:
        """
        取得角色的啟用中 Profile
        
        Args:
            core_id: 角色核心 ID
        
        Returns:
            CharacterProfile or None
        """
        profile = self.db.query(CharacterProfile).filter(
            CharacterProfile.core_id == core_id,
            CharacterProfile.is_active == True
        ).order_by(CharacterProfile.version.desc()).first()
        
        return profile
    
    def get_profile_version(self, core_id: int, version: int) -> Optional[CharacterProfile]:
        """
        取得特定版本的 Profile
        
        Args:
            core_id: 角色核心 ID
            version: 版本號
        
        Returns:
            CharacterProfile or None
        """
        profile = self.db.query(CharacterProfile).filter(
            CharacterProfile.core_id == core_id,
            CharacterProfile.version == version
        ).first()
        
        return profile
