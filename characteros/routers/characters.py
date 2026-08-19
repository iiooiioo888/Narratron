"""CharacterOS 角色路由：查詢與變體請求。"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from sqlalchemy.orm import Session

from characteros.models.database import get_db
from characteros.models.schema import (
    CharacterFullResponse,
    CharacterCoreResponse,
    CharacterVariantResponse,
    VariantQueueResponse,
    ImageGenerateRequest,
    ImageGenerateResponse,
    CharacterEditorResponse,
    CharacterEditorUpdateRequest,
)
from characteros.services.characters import CharacterService
from characteros.services.queue import QueueManager

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
    from characteros.models.orm import CharacterVariant
    
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


@router.post("/{character_id}/images", response_model=ImageGenerateResponse)
def generate_character_images(
    character_id: int,
    body: ImageGenerateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """僅允許 GUI 面板觸發生圖，並依角色風格產出必要參考圖。"""
    from characteros.services.imaging import ImagingService
    panel_header = request.headers.get("X-CharacterOS-Panel", "").strip().lower()
    if panel_header != "enabled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="生圖僅允許從 GUI 面板操作（/admin/panel）",
        )

    service = CharacterService(db)
    full = service.get_character_by_id(character_id)
    manifest: dict = {}
    if full.profile and full.profile.manifest:
        manifest = dict(full.profile.manifest)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"角色 {character_id} 沒有可用的 Profile manifest",
        )
    identity = manifest.setdefault("_identity", {})
    meta = manifest.setdefault("_meta", {})
    identity.setdefault("name", full.core.name)
    meta.setdefault("character_name", full.core.name)
    persist_id = None
    if body.persist:
        persist_id = body.entity_id or str(meta.get("entity_id") or identity.get("entity_id") or f"character-{full.core.name}")
    try:
        payload = ImagingService().generate_for_manifest(
            manifest,
            purpose=body.purpose,
            provider_name=body.provider,
            extra=body.extra,
            n=body.n,
            model=body.model or "",
            base_url=body.base_url or "",
            api_key=body.api_key or "",
            persist_entity_id=persist_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ImageGenerateResponse.model_validate(payload)


@router.get("/{character_id}/editor", response_model=CharacterEditorResponse)
def get_character_editor(
    character_id: int,
    db: Session = Depends(get_db),
):
    """完整角色編輯器讀取：core + active profile。"""
    service = CharacterService(db)
    return service.get_editor_payload(character_id)


@router.put("/{character_id}/editor", response_model=CharacterEditorResponse)
def save_character_editor(
    character_id: int,
    body: CharacterEditorUpdateRequest,
    db: Session = Depends(get_db),
):
    """完整角色編輯器儲存：更新 core + active profile。"""
    service = CharacterService(db)
    return service.update_character_editor(character_id, body)
