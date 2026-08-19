"""CharacterOS ORM：Core（身份錨點）→ Profile（專案設定）→ Variant（變體快取）。"""

from typing import Dict, Any
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, ForeignKey, 
    Text, ARRAY, TIMESTAMP, UniqueConstraint, text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from characteros.models.database import Base


class CharacterCore(Base):
    """
    角色核心身份（不可變）
    儲存角色的基準身份錨點，所有變體都由此衍生
    """
    __tablename__ = 'character_cores'
    
    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), unique=True, nullable=False, server_default=text("uuid_generate_v4()"))
    
    # 核心身份標識
    name = Column(String(255), nullable=False)
    codename = Column(String(100))
    
    # 基礎人口統計
    gender_spectrum = Column(Float, nullable=True)  # CHECK 約束在 DDL 中定義
    base_age = Column(Integer, nullable=False)
    
    # 身份錨點描述（JSONB）
    identity_anchor = Column(JSONB, nullable=False, default=dict)
    
    # 元數據
    tags = Column(ARRAY(Text), default=list)
    meta_info = Column('metadata', JSONB, default=dict)  # 使用 'metadata' 作為欄位名但避免與 SQLAlchemy 保留字衝突
    
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 關聯
    profiles = relationship("CharacterProfile", back_populates="core", cascade="all, delete-orphan")
    variants = relationship("CharacterVariant", back_populates="core", cascade="all, delete-orphan")
    
    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典格式（用於 API 回應）"""
        return {
            "id": self.id,
            "uuid": str(self.uuid),
            "name": self.name,
            "codename": self.codename,
            "gender_spectrum": self.gender_spectrum,
            "base_age": self.base_age,
            "identity_anchor": self.identity_anchor or {},
            "tags": self.tags or [],
            "metadata": self.meta_info or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class CharacterProfile(Base):
    """
    角色專案檔案（可版本化）
    儲存特定專案或時空線的角色設定
    """
    __tablename__ = 'character_profiles'
    __table_args__ = (
        UniqueConstraint('core_id', 'version', name='uq_core_version'),
    )
    
    id = Column(Integer, primary_key=True)
    core_id = Column(Integer, ForeignKey('character_cores.id', ondelete='CASCADE'), nullable=False)
    
    # 版本控制
    version = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)
    
    # 專案特定設定
    project_name = Column(String(255))
    project_id = Column(String(100))
    
    # 完整 Profile Manifest (JSONB)
    manifest = Column(JSONB, nullable=False, default=dict)
    
    # 樣式與外觀設定
    style_preset = Column(String(100))
    outfit_config = Column(JSONB, default=dict)
    
    # 元數據
    created_by = Column(String(100))
    notes = Column(Text)
    
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 關聯
    core = relationship("CharacterCore", back_populates="profiles")
    variants = relationship("CharacterVariant", back_populates="profile")
    
    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典格式"""
        return {
            "id": self.id,
            "core_id": self.core_id,
            "version": self.version,
            "is_active": self.is_active,
            "project_name": self.project_name,
            "project_id": self.project_id,
            "manifest": self.manifest or {},
            "style_preset": self.style_preset,
            "outfit_config": self.outfit_config or {},
            "created_by": self.created_by,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class CharacterVariant(Base):
    """
    角色變體快取（演化結果）
    儲存特定演化參數下的生成結果（或待生成佇列）
    """
    __tablename__ = 'character_variants'
    __table_args__ = (
        UniqueConstraint('core_id', 'variant_hash', name='uq_core_variant_hash'),
    )
    
    id = Column(Integer, primary_key=True)
    core_id = Column(Integer, ForeignKey('character_cores.id', ondelete='CASCADE'), nullable=False)
    profile_id = Column(Integer, ForeignKey('character_profiles.id', ondelete='SET NULL'))
    
    # 變體指紋（唯一性保證）
    variant_hash = Column(String(64), nullable=False)
    
    # 演化參數快照
    evolution_params = Column(JSONB, nullable=False, default=dict)
    
    # 狀態機：pending, ready, failed
    status = Column(String(50), nullable=False, default='pending')
    priority = Column(Integer, default=0)
    
    # 生成結果
    result_url = Column(String(512))
    result_metadata = Column(JSONB, default=dict)
    
    # 錯誤處理
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    
    # 效能指標
    queue_wait_ms = Column(Integer)
    generation_duration_ms = Column(Integer)
    
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 關聯
    core = relationship("CharacterCore", back_populates="variants")
    profile = relationship("CharacterProfile", back_populates="variants")
    
    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典格式"""
        return {
            "id": self.id,
            "core_id": self.core_id,
            "profile_id": self.profile_id,
            "variant_hash": self.variant_hash,
            "evolution_params": self.evolution_params or {},
            "status": self.status,
            "priority": self.priority,
            "result_url": self.result_url,
            "result_metadata": self.result_metadata or {},
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "queue_wait_ms": self.queue_wait_ms,
            "generation_duration_ms": self.generation_duration_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class ImagingConfig(Base):
    """
    生圖設定（singleton，id 固定為 1）
    管理 API 更新後持久化 provider / endpoint / model / api_key。
    """
    __tablename__ = "imaging_config"

    id = Column(Integer, primary_key=True)
    provider = Column(String(50), nullable=False, default="null")
    base_url = Column(String(512), nullable=False)
    model = Column(String(255), nullable=False)
    api_key = Column(Text)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "has_api_key": bool(self.api_key),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class GenerationLog(Base):
    """
    AI 生成日誌（可觀測性）
    記錄每次生成的詳細資訊，用於監控與除錯
    """
    __tablename__ = 'generation_logs'
    
    id = Column(Integer, primary_key=True)
    variant_id = Column(Integer, ForeignKey('character_variants.id', ondelete='SET NULL'))
    trace_id = Column(String(64))
    
    # 模型資訊
    model_used = Column(JSONB, default=dict)
    
    # 參數記錄
    params_used = Column(JSONB, default=dict)
    
    # 效能指標
    generation_duration_ms = Column(Integer)
    queue_wait_duration_ms = Column(Integer)
    total_duration_ms = Column(Integer)
    
    # 品質分數
    quality_score = Column(Float)
    face_similarity = Column(Float)
    anatomy_score = Column(Float)
    
    # 結果
    success = Column(Boolean)
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)
    
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    
    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典格式"""
        return {
            "id": self.id,
            "variant_id": self.variant_id,
            "trace_id": self.trace_id,
            "model_used": self.model_used or {},
            "params_used": self.params_used or {},
            "generation_duration_ms": self.generation_duration_ms,
            "queue_wait_duration_ms": self.queue_wait_duration_ms,
            "total_duration_ms": self.total_duration_ms,
            "quality_score": self.quality_score,
            "face_similarity": self.face_similarity,
            "anatomy_score": self.anatomy_score,
            "success": self.success,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
