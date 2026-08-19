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
    CharacterEditorUpdateRequest,
    CharacterEditorResponse,
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
            joinedload(CharacterCore.profiles)
        ).filter(CharacterCore.id == character_id).first()
        
        if not core:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character with id {character_id} not found"
            )
        
        # 取得 active profile（只取最新啟用版本）
        active_profile = None
        if core.profiles:
            active_profiles = [p for p in core.profiles if p.is_active]
            if active_profiles:
                active_profile = max(active_profiles, key=lambda x: x.version)
        
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

    def get_or_create_active_profile(self, core_id: int) -> CharacterProfile:
        """取得啟用 profile；若不存在則建立 version=1 空白 profile。"""
        profile = self.get_active_profile(core_id)
        if profile:
            return profile

        profile = CharacterProfile(
            core_id=core_id,
            version=1,
            is_active=True,
            manifest={},
        )
        self.db.add(profile)
        self.db.flush()
        return profile

    def get_editor_payload(self, character_id: int) -> CharacterEditorResponse:
        """給 GUI 讀取完整角色編輯資料。"""
        full = self.get_character_by_id(character_id)
        profile = self.get_or_create_active_profile(character_id)
        if not full.profile:
            full = self.get_character_by_id(character_id)
        return CharacterEditorResponse(
            core=full.core,
            profile=CharacterProfileResponse.model_validate(profile),
        )

    def update_character_editor(
        self,
        character_id: int,
        body: CharacterEditorUpdateRequest,
    ) -> CharacterEditorResponse:
        """更新 core + active profile，供完整角色編輯器使用。"""
        core = self.db.query(CharacterCore).filter(CharacterCore.id == character_id).first()
        if not core:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Character with id {character_id} not found",
            )

        profile = self.get_or_create_active_profile(character_id)

        # core fields
        core.name = body.name
        core.codename = body.codename
        core.gender_spectrum = body.gender_spectrum
        core.base_age = body.base_age
        core.identity_anchor = body.identity_anchor or {}
        core.tags = body.tags or []
        core.meta_info = body.metadata or {}

        # profile fields — 內容變更時遞增版本號，確保 variant_hash 不會與舊快取衝突
        import hashlib, json
        old_manifest_hash = hashlib.sha256(
            json.dumps(profile.manifest or {}, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        new_manifest_hash = hashlib.sha256(
            json.dumps(body.manifest or {}, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        if old_manifest_hash != new_manifest_hash:
            profile.version = (profile.version or 1) + 1

        profile.project_name = body.project_name
        profile.project_id = body.project_id
        profile.style_preset = body.style_preset
        profile.outfit_config = body.outfit_config or {}
        profile.created_by = body.created_by
        profile.notes = body.notes
        profile.manifest = body.manifest or {}
        profile.is_active = True

        self.db.add(core)
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(core)
        self.db.refresh(profile)

        return CharacterEditorResponse(
            core=CharacterCoreResponse.model_validate(core),
            profile=CharacterProfileResponse.model_validate(profile),
        )
