"""CharacterOS API 請求／回應的 Pydantic 驗證模式。"""

from __future__ import annotations

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


class CharacterEnsureRequest(BaseModel):
    """建立或取得角色：同名則回傳既有護照，不另開分身。"""

    name: str = Field(..., min_length=1, max_length=255, description="角色名稱；若是一句話簡述會自動膨脹成護照")
    base_age: int = Field(25, ge=0, le=150, description="基準年齡")
    gender_spectrum: Optional[float] = Field(None, ge=0.0, le=1.0, description="性別光譜 (0=女性，1=男性)")
    tags: List[str] = Field(default_factory=list, description="標籤列表")
    notes: Optional[str] = Field(None, max_length=2000, description="備註（例如從劇本摘錄的外觀）")
    brief: Optional[str] = Field(None, max_length=800, description="角色一句話簡述；提供時走敘事自舉")
    manifest: Optional[Dict[str, Any]] = Field(None, description="可選的護照初稿，建立時寫入 Profile")


class CharacterEnsureResponse(CharacterCoreResponse):
    """建立或取得角色的回應。"""

    created: bool = False


class CharacterSyncPassport(BaseModel):
    """從劇本／自舉結果寫入護照的單筆資料。"""

    name: str = Field(..., min_length=1, max_length=255)
    base_age: Optional[int] = Field(None, ge=0, le=150)
    gender_spectrum: Optional[float] = Field(None, ge=0.0, le=1.0)
    tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = Field(None, max_length=4000)
    manifest: Optional[Dict[str, Any]] = None


class CharacterSyncRequest(BaseModel):
    """把劇本解析出的角色名寫入護照。"""

    names: List[str] = Field(default_factory=list, description="角色名稱列表")
    passports: List[CharacterSyncPassport] = Field(default_factory=list, description="可選：帶護照初稿一併寫入")


class CharacterSyncResponse(BaseModel):
    """從劇本同步角色護照的結果。"""

    items: List[CharacterCoreResponse]
    created_count: int = 0
    existing_count: int = 0


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
    weather: Optional[str] = Field(None, description="天氣環境")
    injury_level: Optional[float] = Field(None, ge=0.0, le=1.0, description="受傷程度")
    body_modification: Optional[Dict[str, Any]] = Field(default_factory=dict, description="身體變化")
    custom_params: Dict[str, Any] = Field(default_factory=dict, description="自訂參數")


class CharacterVariantRequest(BaseModel):
    """請求變體生成時的請求格式"""
    age: Optional[int] = Field(None, ge=0, le=150, description="目標年齡")
    emotion: Optional[str] = Field(None, description="情緒狀態")
    scene: Optional[str] = Field(None, description="場景描述")
    weather: Optional[str] = Field(None, description="天氣環境")
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
        """轉換為 .charpass 格式（安全合併，避免 manifest 覆蓋頂層字段）。"""
        result: Dict[str, Any] = {
            "version": "1.0",
            "format": ".charpass",
            "core": self.core.model_dump(),
        }
        
        if self.profile:
            result["active_profile"] = self.profile.model_dump()
            # 將 manifest 嵌套在 manifest 鍵下，避免覆蓋 version / core 等頂層字段
            if self.profile.manifest:
                result["manifest"] = self.profile.manifest
        
        result["variants"] = [v.model_dump() for v in self.available_variants]
        
        return result


# ============================================
# Character Editor Schemas
# ============================================

class CharacterEditorUpdateRequest(BaseModel):
    """完整角色編輯器的儲存請求。"""

    # core
    name: str = Field(..., min_length=1, max_length=255)
    codename: Optional[str] = Field(None, max_length=100)
    gender_spectrum: Optional[float] = Field(None, ge=0.0, le=1.0)
    base_age: int = Field(..., ge=0, le=150)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    identity_anchor: Dict[str, Any] = Field(default_factory=dict)

    # profile
    project_name: Optional[str] = Field(None, max_length=255)
    project_id: Optional[str] = Field(None, max_length=100)
    style_preset: Optional[str] = Field(None, max_length=100)
    outfit_config: Dict[str, Any] = Field(default_factory=dict)
    created_by: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None)
    manifest: Dict[str, Any] = Field(default_factory=dict)


class CharacterEditorResponse(BaseModel):
    """完整角色編輯器的讀取/儲存回應。"""

    core: CharacterCoreResponse
    profile: CharacterProfileResponse


class VersionHistoryItemResponse(BaseModel):
    """角色版本歷史檔案摘要。"""

    name: str
    path: str
    kind: str
    is_binary: bool = False


class VersionBranchSummaryResponse(BaseModel):
    """角色版本分支摘要，供前端穩定呈現 review 與縮圖資訊。"""

    kind: str
    branch_id: str
    label: str
    purpose: Optional[str] = None
    job_id: Optional[str] = None
    status: str
    review_status: Optional[str] = None
    effective_status: Optional[str] = None
    result_url: Optional[str] = None
    asset_paths: List[str] = Field(default_factory=list)
    angles: List[str] = Field(default_factory=list)
    angles_summary: str = ""
    images_by_angle: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    thumbnail_asset_path: Optional[str] = None
    face_detail_asset_path: Optional[str] = None
    hero_asset_path: Optional[str] = None
    representative_asset_path: Optional[str] = None
    representative_angle: Optional[str] = None
    has_face_detail: bool = False
    face_detail_count: int = 0
    face_detail_summary: str = ""
    image_count: int = 0
    purpose_summary: str = ""
    review_label: str = ""
    sort_priority: int = 0
    summary_fields: Dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    sort_key: str = ""
    sort_order: int = 0
    updated_at: Optional[str] = None
    manifest_path: Optional[str] = None
    record_path: Optional[str] = None
    images_index_path: Optional[str] = None
    response_path: Optional[str] = None


class CharacterVersionSummaryResponse(BaseModel):
    """角色版本快照與分支摘要。"""

    entity_id: str
    current_path: str
    history: List[VersionHistoryItemResponse] = Field(default_factory=list)
    branches: List[VersionBranchSummaryResponse] = Field(default_factory=list)


class CharacterAgeAssetItem(BaseModel):
    """單一歲數的面部／T 型資產。"""

    age: int
    face_detail_asset_path: Optional[str] = None
    tpose_asset_path: Optional[str] = None
    face_detail_url: Optional[str] = None
    tpose_url: Optional[str] = None
    has_face_detail: bool = False
    has_tpose: bool = False


class CharacterAgeGalleryResponse(BaseModel):
    """年齡軸圖庫：點選歲數即可預覽面部與 T 型。"""

    character_id: int
    character_name: Optional[str] = None
    age_start: int = 1
    age_end: int = 80
    face_count: int = 0
    tpose_count: int = 0
    items: List[CharacterAgeAssetItem] = Field(default_factory=list)


# ============================================
# Admin & Stats Schemas
# ============================================

class QueueStatsResponse(BaseModel):
    """佇列統計資訊"""
    total_pending: int
    total_waiting: int = 0
    total_running: int = 0
    total_ready: int
    total_failed: int
    average_wait_time_ms: float
    oldest_pending_age_seconds: float


class QueueTaskItem(BaseModel):
    """單一佇列任務（面板列表用）"""
    id: int
    core_id: int
    character_name: Optional[str] = None
    variant_hash: str
    evolution_params: Dict[str, Any] = Field(default_factory=dict)
    status: str
    priority: int = 0
    review_status: Optional[str] = None
    effective_status: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    result_url: Optional[str] = None
    result_metadata: Dict[str, Any] = Field(default_factory=dict)
    purpose: Optional[str] = None
    angles: List[str] = Field(default_factory=list)
    image_count: int = 0
    thumbnail_asset_path: Optional[str] = None
    face_detail_asset_path: Optional[str] = None
    representative_asset_path: Optional[str] = None
    representative_angle: Optional[str] = None
    has_face_detail: bool = False
    face_detail_count: int = 0
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None


class QueueTaskListResponse(BaseModel):
    """佇列任務列表（含統計與儲存模式）"""
    storage_mode: str
    stats: QueueStatsResponse
    tasks: List[QueueTaskItem]
    total: int


class AgeSpanStepStatus(BaseModel):
    """年齡軸單一步驟狀態（供 UI 時間軸顯示）"""
    task_id: Optional[int] = None
    step_index: int = 0
    phase: str = ""
    age: Optional[int] = None
    status: str = "missing"
    error_message: Optional[str] = None


class QueueWorkerCurrentTask(BaseModel):
    """目前正在向 AI 請求的那一筆。"""
    id: int
    core_id: Optional[int] = None
    character_name: Optional[str] = None
    status: str = "running"
    purpose: Optional[str] = None
    phase: Optional[str] = None
    age: Optional[int] = None
    step_index: Optional[int] = None
    total_steps: Optional[int] = None
    started_at: Optional[str] = None
    label: Optional[str] = None


class QueueWorkerStatusResponse(BaseModel):
    """後端逐步生圖 worker 狀態。"""
    paused: bool = False
    busy: bool = False
    auto_run: bool = False
    last_task_id: Optional[int] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    current_task: Optional[QueueWorkerCurrentTask] = None
    pending_count: int = 0
    waiting_count: int = 0
    running_count: int = 0
    failed_count: int = 0


class AgeSpanPipelineStatusResponse(BaseModel):
    """年齡軸／變體 pipeline 進度（按需單齡；fill_span 時才是指定區間）"""
    pipeline_id: Optional[str] = None
    core_id: Optional[int] = None
    character_name: Optional[str] = None
    total_steps: int = 0
    accepted_count: int = 0
    ready_pending_review_count: int = 0
    pending_count: int = 0
    waiting_count: int = 0
    running_count: int = 0
    failed_count: int = 0
    blocking_task_id: Optional[int] = None
    blocking_reason: Optional[str] = None
    next_runnable_task_id: Optional[int] = None
    next_phase: Optional[str] = None
    next_age: Optional[int] = None
    has_open_pipeline: bool = False
    headline: Optional[str] = None
    steps: List[AgeSpanStepStatus] = Field(default_factory=list)


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
    storage_mode: str = "local"


# ============================================
# Imaging Schemas
# ============================================

class ImageProviderInfo(BaseModel):
    name: str
    display_name: str


class GeneratedImageInfo(BaseModel):
    filename: str
    url: Optional[str] = None
    has_bytes: bool = False
    mime_type: str = "image/png"
    angle: Optional[str] = None
    asset_path: Optional[str] = None
    final_asset_path: Optional[str] = None


class ImageGenerateRequest(BaseModel):
    """第三方生圖請求。不傳 provider 時走環境變數 CHARACTEROS_IMAGE_GEN_PROVIDER（預設 null）。"""

    purpose: str = Field("identity", description="identity / face_detail / outfit / expression / thumb / tpose / age_span")
    provider: Optional[str] = Field(None, description="null | http | openai | wan")
    model: Optional[str] = Field(None, description="覆蓋本次生圖模型，例如 wan2.7-image-pro")
    base_url: Optional[str] = Field(
        None,
        description="覆蓋本次生圖端點（例如 https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1）",
    )
    api_key: Optional[str] = Field(
        None,
        description="覆蓋本次生圖 API key（僅本次請求，不寫入資料庫）",
    )
    extra: str = Field("", description="額外拼進正向提示詞的描述")
    n: int = Field(1, ge=1, le=4, description="multi_angle=false 時每次請求張數")
    multi_angle: bool = Field(
        True,
        description="預設 true：依多視角（正／背／左／右／四分之三／頂／底）各生一張；identity 額外補面部細節圖",
    )
    persist: bool = Field(False, description="是否寫回本機 data/charpasses/{entity_id}/")
    entity_id: Optional[str] = Field(None, description="本機護照 entity_id；與 manifest 擇一")
    manifest: Optional[Dict[str, Any]] = Field(None, description="完整 .charpass manifest")


class ImageQueueRequest(BaseModel):
    """把生圖請求包成可由佇列處理的任務。"""

    purpose: str = Field("identity", description="identity / face_detail / outfit / expression / thumb / tpose / age_span")
    provider: Optional[str] = Field(None, description="null | http | openai | wan")
    model: Optional[str] = Field(None, description="覆蓋本次生圖模型")
    base_url: Optional[str] = Field(None, description="覆蓋本次生圖端點")
    api_key: Optional[str] = Field(None, description="覆蓋本次生圖 API key")
    extra: str = Field("", description="額外拼進正向提示詞的描述")
    n: int = Field(1, ge=1, le=4)
    multi_angle: bool = Field(True, description="是否使用多視角生圖")
    persist: bool = Field(True, description="是否將圖片與完整回應寫回角色資料夾")
    entity_id: Optional[str] = Field(None, description="指定持久化 entity_id")
    age: Optional[int] = Field(None, ge=0, le=150, description="目標年齡")
    age_start: Optional[int] = Field(None, ge=1, le=80, description="年齡軸起始歲數（fill_span 時使用）")
    age_end: Optional[int] = Field(None, ge=1, le=80, description="年齡軸結束歲數（fill_span 時使用）")
    fill_span: bool = Field(False, description="是否補齊指定 age_start–age_end 區間；預設關閉，且不會自動假設 1–80")
    emotion: Optional[str] = Field(None, description="情緒狀態")
    scene: Optional[str] = Field(None, description="場景描述")
    weather: Optional[str] = Field(None, description="天氣環境")
    injury: Optional[float] = Field(None, ge=0.0, le=1.0, description="受傷程度")
    priority: int = Field(0, ge=0, le=10, description="佇列優先級")
    auto_accept: bool = Field(True, description="生圖完成後自動接受入庫（年齡軸建議開啟）")


class ImageGenerateResponse(BaseModel):
    provider: str
    model: str = ""
    purpose: str
    prompt: str
    negative_prompt: str = ""
    ref_image_uris: List[str] = Field(default_factory=list)
    multi_angle: bool = True
    angles: List[str] = Field(default_factory=list)
    images: List[GeneratedImageInfo] = Field(default_factory=list)
    images_by_angle: Dict[str, List[GeneratedImageInfo]] = Field(default_factory=dict)
    face_detail_images: List[GeneratedImageInfo] = Field(default_factory=list)
    thumbnail_image: Optional[GeneratedImageInfo] = None
    thumbnail_asset_path: Optional[str] = None
    face_detail_asset_path: Optional[str] = None
    face_detail_count: int = 0
    review: Dict[str, Any] = Field(default_factory=dict)
    review_status: Optional[str] = None
    manifest: Dict[str, Any] = Field(default_factory=dict)


class ImagingConfigResponse(BaseModel):
    provider: str
    base_url: str
    model: str
    has_api_key: bool


class ImagingConfigUpdateRequest(BaseModel):
    provider: Optional[str] = Field(None, description="null | http | openai | wan")
    base_url: Optional[str] = Field(None, description="生圖 API base URL（wan 可填 compatible-mode/v1）")
    model: Optional[str] = Field(None, description="預設生圖模型")
    api_key: Optional[str] = Field(None, description="生圖 API key")
    clear_api_key: bool = Field(False, description="是否清除已儲存的 API key")
    persist_env: bool = Field(True, description="是否同步寫入 repo 根目錄 .env")
