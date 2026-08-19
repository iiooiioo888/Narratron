"""
Narratron CharacterOS - Characters Router
核心 API：角色查詢與變體請求
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schemas import (
    CharacterFullResponse,
    CharacterCoreResponse,
    CharacterVariantResponse,
    CharacterVariantRequest,
    VariantQueueResponse
)
from app.services.character_service import CharacterService
from app.services.evolution_engine import EvolutionEngine
from app.services.queue_manager import QueueManager

router = APIRouter(prefix="/api/v1/characters", tags=["Characters"])


@router.get("", response_model=List[CharacterCoreResponse])
def list_characters(
    skip: int = Query(0, ge=0, description="跳過數量（分頁）"),
    limit: int = Query(20, ge=1, le=100, description="返回數量上限"),
    name: Optional[str] = Query(None, description="名稱模糊搜尋"),
    tags: Optional[List[str]] = Query(None, description="標籤過濾"),
    db: Session = Depends(get_db)
):
    """
    列出所有角色（摘要資訊）
    
    - **skip**: 分頁跳過數量
    - **limit**: 每頁返回數量（最大 100）
    - **name**: 名稱模糊搜尋
    - **tags**: 標籤過濾（包含任一標籤即可）
    """
    service = CharacterService(db)
    result = service.list_characters(
        skip=skip,
        limit=limit,
        name_filter=name,
        tags_filter=tags
    )
    
    return result["items"]


@router.get("/{character_id}", response_model=CharacterFullResponse)
def get_character(
    character_id: int,
    db: Session = Depends(get_db)
):
    """
    取得角色完整資訊（Core + Active Profile）
    
    回傳 `.charpass` 格式的完整角色檔案，包含：
    - 核心身份（不可變）
    - 當前啟用的 Profile（可版本化）
    - 已生成的變體列表（status='ready'）
    
    **不存在即 404**：不會自動創建角色
    """
    service = CharacterService(db)
    return service.get_character_by_id(character_id)


@router.get("/{character_id}/variant", response_model=CharacterVariantResponse | VariantQueueResponse)
def request_variant(
    character_id: int,
    age: Optional[int] = Query(None, ge=0, le=150, description="目標年齡"),
    emotion: Optional[str] = Query(None, description="情緒狀態"),
    scene: Optional[str] = Query(None, description="場景描述"),
    injury: Optional[float] = Query(None, ge=0.0, le=1.0, description="受傷程度"),
    priority: int = Query(0, ge=0, le=10, description="優先級"),
    db: Session = Depends(get_db)
):
    """
    請求角色的進化變體
    
    **核心邏輯**：
    1. 檢查角色是否存在（不存在則 404）
    2. 計算演化參數的 variant_hash
    3. 若變體已存在且 ready → 回傳 200 + 完整變體資訊
    4. 若變體已存在但 pending → 回傳 202 + queue_id
    5. 若變體不存在 → 寫入 pending 佇列，回傳 202 + queue_id
    
    **演化參數**：
    - `age`: 目標年齡（覆蓋基準年齡）
    - `emotion`: 情緒狀態（neutral, happy, sad, angry, fearful, determined）
    - `scene`: 場景上下文（battle, formal_event, casual_street, post_apocalyptic）
    - `injury`: 受傷程度（0.0-1.0）
    - `priority`: 生成優先級（0-10）
    
    **回應碼**：
    - `200 OK`: 變體已生成完成
    - `202 Accepted`: 變體已排入佇列，等待背景處理
    - `404 Not Found`: 角色不存在
    """
    # 1. 組建演化參數
    evolution_params = {}
    if age is not None:
        evolution_params['age_override'] = age
    if emotion is not None:
        evolution_params['emotion_state'] = emotion
    if scene is not None:
        evolution_params['scene_context'] = scene
    if injury is not None:
        evolution_params['injury_level'] = injury
    
    # 2. 使用 QueueManager 處理冪等性與佇列寫入
    queue_mgr = QueueManager(db)
    variant, is_new = queue_mgr.request_variant_generation(
        core_id=character_id,
        evolution_params=evolution_params,
        priority=priority
    )
    
    # 3. 根據狀態決定回應
    if variant.status == 'ready':
        # 已生成完成，回傳 200
        return CharacterVariantResponse.model_validate(variant)
    else:
        # pending 或 failed，回傳 202
        # （failed 的變體理論上不應被用戶直接請求，此處僅做保護）
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail={
                "message": "Variant generation queued",
                "queue_id": variant.id,
                "variant_hash": variant.variant_hash,
                "status": variant.status,
                "estimated_wait_seconds": 300
            },
            headers={
                "Retry-After": "300",
                "Location": f"/api/v1/characters/{character_id}/variant"
            }
        )


@router.get("/{character_id}/variants", response_model=List[CharacterVariantResponse])
def list_character_variants(
    character_id: int,
    status_filter: Optional[str] = Query(None, description="狀態過濾 (pending, ready, failed)"),
    db: Session = Depends(get_db)
):
    """
    列出角色的所有變體（含待處理佇列）
    
    可用於監控生成進度或查看歷史變體
    """
    from app.models.orm import CharacterVariant
    
    query = db.query(CharacterVariant).filter(
        CharacterVariant.core_id == character_id
    )
    
    if status_filter:
        query = query.filter(CharacterVariant.status == status_filter)
    
    variants = query.order_by(CharacterVariant.created_at.desc()).limit(100).all()
    
    # 驗證角色存在（若不存在應 404）
    service = CharacterService(db)
    service.get_character_by_id(character_id)  # 僅用於驗證存在性
    
    return [CharacterVariantResponse.model_validate(v) for v in variants]
