"""
Narratron CharacterOS - Pydantic Schemas
用於 API 請求/回應的資料驗證與序列化
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime


# ============================================
# Core Schemas
# ============================================

class CharacterCoreBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="角色名稱")
    codename: Optional[str] = Field(None, max_length=100, description="角色代號")
    gender_spectrum: Optional[float] = Field(None, ge=0.0, le=1.0, description="性別光譜 (0=女性，1=男性)")
    base_age: int = Field(..., ge=0, le=150, description="基準年齡")
    identity_anchor: Dict[str, Any] = Field(default_factory=dict, description="身份錨點描述")
    tags: List[str] = Field(default_factory=list, description="標籤列表")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元數據")


class CharacterCoreCreate(CharacterCoreBase):
    """創建角色核心時的請求格式"""
    pass


class CharacterCoreResponse(CharacterCoreBase):
    """角色核心的回應格式"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    uuid: str
    created_at: datetime
    updated_at: datetime


# ============================================
# Profile Schemas
# ============================================

class CharacterProfileBase(BaseModel):
    version: int = Field(1, ge=1, description="版本號")
    is_active: bool = Field(True, description="是否為啟用狀態")
    project_name: Optional[str] = Field(None, max_length=255, description="專案名稱")
    project_id: Optional[str] = Field(None, max_length=100, description="專案 ID")
    manifest: Dict[str, Any] = Field(default_factory=dict, description="完整 Profile Manifest")
    style_preset: Optional[str] = Field(None, max_length=100, description="樣式預設")
    outfit_config: Dict[str, Any] = Field(default_factory=dict, description="服裝配置")
    created_by: Optional[str] = Field(None, max_length=100, description="創建者")
    notes: Optional[str] = Field(None, description="備註")


class CharacterProfileCreate(CharacterProfileBase):
    """創建角色檔案時的請求格式"""
    core_id: int


class CharacterProfileResponse(CharacterProfileBase):
    """角色檔案的回應格式"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    core_id: int
    created_at: datetime
    updated_at: datetime


# ============================================
# Variant Schemas
# ============================================

class VariantEvolutionParams(BaseModel):
    """變體演化參數"""
    age_override: Optional[int] = Field(None, ge=0, le=150, description="年齡覆蓋值")
    emotion_state: Optional[str] = Field(None, description="情緒狀態")
    scene_context: Optional[str] = Field(None, description="場景上下文")
    injury_level: Optional[float] = Field(None, ge=0.0, le=1.0, description="受傷程度")
    body_modification: Optional[Dict[str, Any]] = Field(default_factory=dict, description="身體變化")
    custom_params: Dict[str, Any] = Field(default_factory=dict, description="自訂參數")


class CharacterVariantRequest(BaseModel):
    """請求變體生成時的請求格式"""
    age: Optional[int] = Field(None, ge=0, le=150, description="目標年齡")
    emotion: Optional[str] = Field(None, description="情緒狀態")
    scene: Optional[str] = Field(None, description="場景描述")
    injury: Optional[float] = Field(None, ge=0.0, le=1.0, description="受傷程度")
    modifications: Optional[Dict[str, Any]] = Field(default_factory=dict, description="身體變化")
    priority: int = Field(0, ge=0, le=10, description="優先級 (0-10)")


class CharacterVariantResponse(BaseModel):
    """變體的回應格式"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    core_id: int
    profile_id: Optional[int]
    variant_hash: str
    evolution_params: Dict[str, Any]
    status: str  # pending, ready, failed
    priority: int
    result_url: Optional[str]
    result_metadata: Dict[str, Any]
    error_message: Optional[str]
    retry_count: int
    max_retries: int
    queue_wait_ms: Optional[int]
    generation_duration_ms: Optional[int]
    created_at: datetime
    updated_at: datetime


class VariantQueueResponse(BaseModel):
    """變體佇列回應（202 Accepted）"""
    message: str = "Variant generation queued"
    queue_id: int
    variant_hash: str
    status: str = "pending"
    estimated_wait_seconds: int = 300  # 預估等待時間（秒）


# ============================================
# Combined Response Schemas
# ============================================

class CharacterFullResponse(BaseModel):
    """角色完整資訊回應（Core + Active Profile）"""
    model_config = ConfigDict(from_attributes=True)
    
    core: CharacterCoreResponse
    profile: Optional[CharacterProfileResponse] = None
    available_variants: List[CharacterVariantResponse] = Field(default_factory=list)
    
    def to_charpass_format(self) -> Dict[str, Any]:
        """轉換為 .charpass 格式"""
        result = {
            "version": "1.0",
            "format": ".charpass",
            "core": self.core.model_dump(),
        }
        
        if self.profile:
            result["active_profile"] = self.profile.model_dump()
            # 合併 manifest 到頂層以便於使用
            if self.profile.manifest:
                result.update(self.profile.manifest)
        
        result["variants"] = [v.model_dump() for v in self.available_variants]
        
        return result


# ============================================
# Admin & Stats Schemas
# ============================================

class QueueStatsResponse(BaseModel):
    """佇列統計資訊"""
    total_pending: int
    total_ready: int
    total_failed: int
    average_wait_time_ms: float
    oldest_pending_age_seconds: float


class SystemMetricsResponse(BaseModel):
    """系統效能指標"""
    database_connections: int
    cache_hit_rate: float
    api_response_time_p95_ms: float
    total_characters: int
    total_profiles: int
    total_variants: int


class HealthCheckResponse(BaseModel):
    """健康檢查回應"""
    status: str  # healthy, degraded, unhealthy
    database: str  # connected, disconnected
    timestamp: datetime
