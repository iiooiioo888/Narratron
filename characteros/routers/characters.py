"""CharacterOS 角色路由：查詢與變體請求。"""

from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from characteros.deps import CharacterBackend, get_character_backend
from characteros.models.database import get_db
from characteros.models.schema import (
    CharacterFullResponse,
    CharacterCoreResponse,
    CharacterVariantResponse,
    VariantQueueResponse,
    ImageGenerateRequest,
    ImageQueueRequest,
    ImageGenerateResponse,
    CharacterEditorResponse,
    CharacterEditorUpdateRequest,
    CharacterVersionSummaryResponse,
    CharacterAgeGalleryResponse,
    CharacterEnsureRequest,
    CharacterEnsureResponse,
    CharacterSyncRequest,
    CharacterSyncResponse,
    CharacterSyncPassport,
)
from characteros.services.characters import CharacterService
from characteros.services.queue import QueueManager
from characteros.storage.db_availability import is_database_available
from characteros.storage.local_characters import LocalCharacterService
from characteros.storage.local_queue import LocalQueueManager
from characteros.services.image_pipeline import enqueue_character_images
from narratron.charpass.store import CharpassStore

router = APIRouter(prefix="/api/v1/characters", tags=["Characters"])


def _manifest_dict(service: CharacterBackend, character_id: int) -> dict:
    full = service.get_character_by_id(character_id)
    if full.profile and full.profile.manifest:
        return dict(full.profile.manifest)
    return {}


def _resolve_local_asset_path(character_id: int, asset_path: str, service: CharacterBackend) -> Path:
    manifest = _manifest_dict(service, character_id)
    meta = manifest.get("_meta") or {}
    identity = manifest.get("_identity") or {}
    entity_id = str(meta.get("entity_id") or identity.get("entity_id") or "").strip()
    if not entity_id:
        name = str(identity.get("name") or meta.get("character_name") or f"character-{character_id}").strip()
        entity_id = f"character-{name}"

    cleaned = str(asset_path or "").replace("\\", "/").lstrip("/")
    rel = Path(cleaned)
    parts = list(rel.parts)
    if (
        not cleaned
        or rel.is_absolute()
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    root = CharpassStore().entity_dir(entity_id).resolve()
    target = (root.joinpath(*parts)).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found") from exc
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return target


@router.get("", response_model=List[CharacterCoreResponse])
def list_characters(
    skip: int = Query(0, ge=0, description="跳過數量（分頁）"),
    limit: int = Query(20, ge=1, le=100, description="返回數量上限"),
    name: Optional[str] = Query(None, description="名稱模糊搜尋"),
    tags: Optional[List[str]] = Query(None, description="標籤過濾"),
    service: CharacterBackend = Depends(get_character_backend),
):
    """
    列出所有角色（摘要資訊）
    
    - **skip**: 分頁跳過數量
    - **limit**: 每頁返回數量（最大 100）
    - **name**: 名稱模糊搜尋
    - **tags**: 標籤過濾（包含任一標籤即可）
    """
    result = service.list_characters(
        skip=skip,
        limit=limit,
        name_filter=name,
        tags_filter=tags
    )
    
    return result["items"]


@router.post("", response_model=CharacterEnsureResponse)
def ensure_character(
    body: CharacterEnsureRequest,
    service: CharacterBackend = Depends(get_character_backend),
):
    """建立角色護照；同名則回傳既有角色，不另開分身。"""
    core, created = service.ensure_character(
        body.name,
        base_age=body.base_age,
        gender_spectrum=body.gender_spectrum,
        tags=body.tags,
        notes=body.notes,
        brief=body.brief,
        manifest=body.manifest,
    )
    payload = core.model_dump()
    payload["created"] = created
    return payload


@router.post("/sync-from-script", response_model=CharacterSyncResponse)
def sync_characters_from_script(
    body: CharacterSyncRequest,
    service: CharacterBackend = Depends(get_character_backend),
):
    """把劇本解析到的角色名寫入護照（Dashboard 子面板用，不是第六個畫面）。"""
    items: list[CharacterCoreResponse] = []
    created_count = 0
    seen: set[str] = set()
    incoming: list[CharacterSyncPassport] = list(body.passports or [])
    named = {str(item.name or "").strip() for item in incoming}
    for raw in body.names:
        name = str(raw or "").strip()
        if not name or name in named:
            continue
        incoming.append(CharacterSyncPassport(name=name))
        named.add(name)
    for passport in incoming:
        name = str(passport.name or "").strip()
        if not name:
            continue
        key = name.lower() if name.isascii() else name
        if key in seen:
            continue
        seen.add(key)
        core, created = service.ensure_character(
            name,
            base_age=passport.base_age if passport.base_age is not None else 25,
            gender_spectrum=passport.gender_spectrum,
            tags=passport.tags,
            notes=passport.notes,
            manifest=passport.manifest,
        )
        items.append(core)
        if created:
            created_count += 1
    return CharacterSyncResponse(
        items=items,
        created_count=created_count,
        existing_count=len(items) - created_count,
    )


@router.get("/{character_id}", response_model=CharacterFullResponse)
def get_character(
    character_id: int,
    service: CharacterBackend = Depends(get_character_backend),
):
    """
    取得角色完整資訊（Core + Active Profile）
    
    回傳 `.charpass` 格式的完整角色檔案，包含：
    - 核心身份（不可變）
    - 當前啟用的 Profile（可版本化）
    - 已生成的變體列表（status='ready'）
    
    **不存在即 404**：不會自動創建角色
    """
    return service.get_character_by_id(character_id)


@router.get("/{character_id}/variant", response_model=CharacterVariantResponse | VariantQueueResponse)
def request_variant(
    character_id: int,
    age: Optional[int] = Query(None, ge=0, le=150, description="目標年齡"),
    emotion: Optional[str] = Query(None, description="情緒狀態"),
    scene: Optional[str] = Query(None, description="場景描述"),
    weather: Optional[str] = Query(None, description="天氣環境"),
    injury: Optional[float] = Query(None, ge=0.0, le=1.0, description="受傷程度"),
    purpose: Optional[str] = Query(
        None,
        description="生圖用途：face_detail / tpose / age_span / identity；有 age 時預設 face_detail",
    ),
    priority: int = Query(0, ge=0, le=10, description="優先級"),
    queue_nonce: Optional[str] = Query(
        None,
        description="僅除錯用：強制產生新任務。預設依 variant_hash 冪等復用快取。",
    ),
    service: CharacterBackend = Depends(get_character_backend),
    db: Session = Depends(get_db),
):
    """
    請求角色的進化變體（按需、快取復用）

    **核心邏輯**：
    1. 檢查角色是否存在（不存在則 404）
    2. 以 core_id + profile_version + 語意參數計算 variant_hash
    3. 若變體已存在且 ready → 回傳 200 + 完整變體資訊（含 result_url）
    4. 若變體已存在但 pending → 回傳 202 + queue_id
    5. 若變體不存在 → 寫入 pending 佇列，回傳 202 + queue_id

    **演化參數**：
    - `age`: 目標年齡（覆蓋基準年齡；只生成該歲，不跑 1→80）
    - `emotion`: 情緒狀態（neutral, happy, sad, angry, fearful, determined）
    - `scene`: 場景上下文（battle, formal_event, casual_street, post_apocalyptic）
    - `weather`: 天氣（clear, rain, snow, fog, night, storm）
    - `injury`: 受傷程度（0.0-1.0）
    - `purpose`: 生圖用途
    - `priority`: 生成優先級（0-10）
    """
    resolved_purpose = str(purpose or "").strip() or ("face_detail" if age is not None else "identity")
    evolution_params: dict = {}
    if age is not None:
        evolution_params["age_override"] = age
    if emotion is not None:
        evolution_params["emotion_state"] = emotion
    if scene is not None:
        evolution_params["scene_context"] = scene
    if weather is not None:
        evolution_params["weather"] = weather
    if injury is not None:
        evolution_params["injury_level"] = injury
    evolution_params["purpose"] = resolved_purpose
    if queue_nonce:
        evolution_params["_queue_nonce"] = queue_nonce

    if resolved_purpose == "age_span" or (age is not None and resolved_purpose in {"face_detail", "tpose", "age_span"}):
        from characteros.services.age_span import (
            FACE_PHASE,
            TPOSE_PHASE,
            age_span_steps,
            build_age_span_evolution_params,
            new_pipeline_id,
        )

        target_age = age
        if target_age is None:
            preview = service.get_character_by_id(character_id)
            target_age = int(preview.core.base_age) if preview.core and preview.core.base_age is not None else 25
        steps = age_span_steps(age=int(target_age), fill_span=False)
        if resolved_purpose == TPOSE_PHASE:
            steps = [item for item in steps if item.get("phase") == TPOSE_PHASE] or steps[-1:]
        elif resolved_purpose == FACE_PHASE:
            steps = [item for item in steps if item.get("phase") == FACE_PHASE] or steps[:1]
        step = steps[0]
        evolution_params = build_age_span_evolution_params(
            step,
            pipeline_id=new_pipeline_id(),
            extra="",
            persist=True,
            emotion=emotion,
            scene=scene,
            weather=weather,
            injury=injury,
        )
        if queue_nonce:
            evolution_params["_queue_nonce"] = queue_nonce

    if isinstance(service, LocalCharacterService) or not is_database_available():
        from datetime import datetime, timezone

        def _as_dt(value):
            if isinstance(value, datetime):
                return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            if isinstance(value, str) and value.strip():
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc)

        full = service.get_character_by_id(character_id)
        char_name = full.core.name if full and full.core else None
        queue_mgr = LocalQueueManager()
        task, _is_new = queue_mgr.request_variant_generation(
            core_id=character_id,
            evolution_params=evolution_params,
            priority=priority,
            character_name=char_name,
        )
        if task.get("status") == "ready":
            return CharacterVariantResponse(
                id=int(task["id"]),
                core_id=int(task["core_id"]),
                profile_id=None,
                variant_hash=str(task["variant_hash"]),
                evolution_params=task.get("evolution_params") or {},
                status=str(task["status"]),
                priority=int(task.get("priority") or 0),
                result_url=task.get("result_url"),
                result_metadata=task.get("result_metadata") or {},
                error_message=task.get("error_message"),
                retry_count=int(task.get("retry_count") or 0),
                max_retries=int(task.get("max_retries") or 3),
                queue_wait_ms=task.get("queue_wait_ms"),
                generation_duration_ms=task.get("generation_duration_ms"),
                created_at=_as_dt(task.get("created_at")),
                updated_at=_as_dt(task.get("updated_at")),
            )
        from characteros.services.queue_worker import resume_and_wake_queue_worker

        resume_and_wake_queue_worker()
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail={
                "message": "Variant generation queued (local mode — DB unavailable)",
                "queue_id": int(task["id"]),
                "variant_hash": str(task["variant_hash"]),
                "status": str(task.get("status") or "pending"),
                "estimated_wait_seconds": 0,
            },
            headers={
                "Retry-After": "0",
                "Location": f"/api/v1/characters/{character_id}/variant",
            },
        )

    # 2. 使用 QueueManager 處理冪等性與佇列寫入
    queue_mgr = QueueManager(db)
    variant, is_new = queue_mgr.request_variant_generation(
        core_id=character_id,
        evolution_params=evolution_params,
        priority=priority
    )
    
    # 3. 根據狀態決定回應
    if variant.status == 'ready':
        return CharacterVariantResponse.model_validate(variant)

    from characteros.services.queue_worker import resume_and_wake_queue_worker

    resume_and_wake_queue_worker()
    raise HTTPException(
        status_code=status.HTTP_202_ACCEPTED,
        detail={
            "message": "Variant generation queued",
            "queue_id": variant.id,
            "variant_hash": variant.variant_hash,
            "status": variant.status,
            "estimated_wait_seconds": 300,
        },
        headers={
            "Retry-After": "300",
            "Location": f"/api/v1/characters/{character_id}/variant",
        },
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
    service: CharacterBackend = Depends(get_character_backend),
):
    """僅允許 GUI 面板觸發生圖，並依角色風格產出必要參考圖。"""
    from characteros.services.imaging import ImagingService
    panel_header = request.headers.get("X-CharacterOS-Panel", "").strip().lower()
    if panel_header != "enabled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="生圖僅允許從 GUI 面板操作（/admin/panel）",
        )

    full = service.get_character_by_id(character_id)
    manifest: dict = {}
    if full.profile and full.profile.manifest:
        manifest = dict(full.profile.manifest)
    # manifest 可允許為空：ImagingService 會自動補齊預設的
    # `_style.character_style.visual`，以便在「尚未手動填完 manifest」時仍可生圖。
    identity = manifest.setdefault("_identity", {})
    meta = manifest.setdefault("_meta", {})
    identity.setdefault("name", full.core.name)
    meta.setdefault("character_name", full.core.name)
    persist_id = None
    if body.persist:
        persist_id = body.entity_id or str(meta.get("entity_id") or identity.get("entity_id") or f"character-{full.core.name}")
    # API key 優先從 header 讀取，避免明文出現在請求體／瀏覽器歷史
    api_key = request.headers.get("X-Image-Gen-Api-Key", "") or body.api_key or ""
    try:
        extra_fields = {}
        if getattr(body, "lora", None):
            extra_fields["lora"] = body.lora
        payload = ImagingService().generate_for_manifest(
            manifest,
            purpose=body.purpose,
            provider_name=body.provider,
            extra=body.extra,
            n=body.n,
            model=body.model or "",
            base_url=body.base_url or "",
            api_key=api_key,
            persist_entity_id=persist_id,
            multi_angle=body.multi_angle,
            extra_fields=extra_fields or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ImageGenerateResponse.model_validate(payload)


@router.post("/{character_id}/image-queue")
def queue_character_image_generation(
    character_id: int,
    body: ImageQueueRequest,
    request: Request,
    service: CharacterBackend = Depends(get_character_backend),
    db: Session = Depends(get_db),
):
    """把生圖工作排入佇列；預設按需生成目標變體，fill_span 才補齊指定區間。"""
    panel_header = request.headers.get("X-CharacterOS-Panel", "").strip().lower()
    if panel_header != "enabled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="生圖佇列僅允許從 GUI 面板操作（/admin/panel）",
        )
    try:
        return enqueue_character_images(
            character_id=character_id,
            body=body,
            service=service,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/{character_id}/editor", response_model=CharacterEditorResponse)
def get_character_editor(
    character_id: int,
    service: CharacterBackend = Depends(get_character_backend),
):
    """完整角色編輯器讀取：core + active profile。"""
    return service.get_editor_payload(character_id)


@router.get("/{character_id}/charpass")
def get_character_charpass(
    character_id: int,
    service: CharacterBackend = Depends(get_character_backend),
):
    """取得角色目前可讀 charpass manifest。"""
    return {"charpass": _manifest_dict(service, character_id)}


@router.post("/{character_id}/charpass")
def save_character_charpass(
    character_id: int,
    body: dict,
    service: CharacterBackend = Depends(get_character_backend),
):
    """直接儲存角色目前 charpass，供前端面板寫回 JSON 護照。"""
    manifest = body.get("charpass") if isinstance(body, dict) else None
    if not isinstance(manifest, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="body.charpass must be an object",
        )
    saved = service.save_charpass(character_id, manifest)
    return {"charpass": saved}


@router.get("/{character_id}/versions", response_model=CharacterVersionSummaryResponse)
def get_character_versions(
    character_id: int,
    service: CharacterBackend = Depends(get_character_backend),
):
    """取得角色目前版本快照與分支摘要。"""
    return service.get_version_summary(character_id)


@router.get("/{character_id}/age-gallery", response_model=CharacterAgeGalleryResponse)
def get_character_age_gallery(
    character_id: int,
    age_start: int = Query(1, ge=1, le=80, description="起始歲數"),
    age_end: int = Query(80, ge=1, le=80, description="結束歲數"),
    service: CharacterBackend = Depends(get_character_backend),
):
    """依歲數回傳面部／T 型資產，供點選年齡預覽。"""
    if age_end < age_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="age_end must be >= age_start",
        )
    return service.get_age_gallery(character_id, age_start=age_start, age_end=age_end)


@router.get("/{character_id}/assets/{asset_path:path}")
def get_character_asset(
    character_id: int,
    asset_path: str,
    service: CharacterBackend = Depends(get_character_backend),
):
    """唯讀提供角色本機資產，供面板預覽已生成圖片。"""
    target = _resolve_local_asset_path(character_id, asset_path, service)
    return FileResponse(target)


@router.put("/{character_id}/editor", response_model=CharacterEditorResponse)
def save_character_editor(
    character_id: int,
    body: CharacterEditorUpdateRequest,
    service: CharacterBackend = Depends(get_character_backend),
):
    """完整角色編輯器儲存：更新 core + active profile。"""
    return service.update_character_editor(character_id, body)
