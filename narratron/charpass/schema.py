"""Character Passport（`.charpass`）Pydantic v2 模型。

未知欄位以 `extra="allow"` 原樣保留，符合 v1.0「前向相容、不丟欄位」。
核心讀寫契約見 `docs/charpass.md`。核心 **不讀不改** `_extensions`。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

FORMAT_NAME: str = "Character Passport"
FORMAT_STEM: str = "charpass"
FORMAT_EXTENSION: str = ".charpass"
FORMAT_VERSION: str = "1.0.0"
PARSER_VERSION: str = "1.0.0"
MIME_TYPE: str = "application/x-narratron-charpass"
SCHEMA_URI: str = "https://narratron.dev/schemas/charpass/v1.json"
LITE_THRESHOLD_BYTES: int = 50 * 1024 * 1024
MAX_STORED_VERSIONS: int = 5
CHARPASS_ID_SHORT_LEN: int = 6
# 本機版本庫：`current.charpass` 為 L0 可讀 JSON；`history/` 與匯出仍為 ZIP 二進位
LOCAL_CURRENT_FILE: str = "current.charpass"
READABLE_SIDECAR: str = LOCAL_CURRENT_FILE
LEGACY_READABLE_SIDECAR: str = "current.manifest.json"
LEGACY_MANIFEST_SIDECAR: str = "manifest.json"
READABLE_SIDECAR_HINT: str = (
    "本機 L0 可讀 JSON 角色護照，可直接在 IDE 檢視／編輯。"
    "匯出或寫入 history/ 時會打包成 ZIP 二進位 .charpass。"
)


def is_json_charpass(data: bytes) -> bool:
    """本機 L0 可讀 JSON（非 ZIP 容器）。"""
    if not data:
        return False
    start = data.lstrip()
    if start.startswith(b"\xef\xbb\xbf"):
        start = start[3:].lstrip()
    return start.startswith(b"{")


def strip_local_sidecar(manifest: dict[str, Any]) -> dict[str, Any]:
    """移除本機 `_local` 提示，供打包／校驗用。"""
    if not isinstance(manifest, dict):
        return {}
    return {key: value for key, value in manifest.items() if key != "_local"}


PackMode = Literal["full", "lite"]
EncryptionLevel = Literal["L0", "L1", "L2", "L3"]
ConflictStrategy = Literal["create_new", "merge", "overwrite"]
LicenseKind = Literal["project_internal", "team_shared", "public", "encrypted"]

LAYER_KEYS: tuple[str, ...] = (
    "_meta",
    "_identity",
    "_body",
    "_style",
    "_expression",
    "_pose",
    "_physics",
    "_voice",
    "_causal",
    "_constraints",
    "_extensions",
)

_ENCRYPTION_TO_INT: dict[str, int] = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
_INT_TO_ENCRYPTION: dict[int, EncryptionLevel] = {0: "L0", 1: "L1", 2: "L2", 3: "L3"}


def encryption_level_to_int(level: EncryptionLevel | int | str | None) -> int:
    if level is None:
        return 0
    if isinstance(level, int):
        if level not in _INT_TO_ENCRYPTION:
            raise ValueError(f"不支援的 encryption_level={level}")
        return level
    text = str(level).strip().upper()
    if text in _ENCRYPTION_TO_INT:
        return _ENCRYPTION_TO_INT[text]
    if text.isdigit():
        return encryption_level_to_int(int(text))
    raise ValueError(f"不支援的 encryption_level={level}")


def encryption_level_to_label(level: EncryptionLevel | int | str | None) -> EncryptionLevel:
    return _INT_TO_ENCRYPTION[encryption_level_to_int(level)]


class LayerBase(BaseModel):
    """各層共用：允許未知欄位並在 dump 時保留。"""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class AssetRef(LayerBase):
    id: str = ""
    kind: str = "reference_image"
    path: str = ""
    uri: str = ""
    embedded: str | None = None
    angle: str | None = None
    weight: float | None = None
    note: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class FaceEmbedding(LayerBase):
    path: str = ""
    model: str = ""
    dimension: int = 512
    dtype: str = "float32"


class IpAdapter(LayerBase):
    enabled: bool = True
    model: str = "ip-adapter-faceid-plusv2"
    weight: float = 0.85
    noise_aug: float = 0.02


class Blend(LayerBase):
    mode: Literal["single", "multi"] = "single"
    sources: list[Any] = Field(default_factory=list)
    ethnicity_bias: float = 0.0
    gender_spectrum: float = 0.5
    age_offset: int = 0
    age_visual: int | None = None


class LockRules(LayerBase):
    face_consistency_threshold: float = 0.88
    allow_expression_change: bool = True
    allow_aging_progression: bool = True
    forbidden_regions: list[str] = Field(default_factory=list)


class DamageRegion(LayerBase):
    id: str = ""
    token: str = ""
    area: str = ""
    region: str = "unspecified"
    type: str = ""
    intensity: float | None = None
    since_scene: int | None = None
    description: str = ""
    note: str = ""
    source: str = "manual"


class PhysicalParams(LayerBase):
    reflectance: float = 0.0
    roughness: float = 0.5
    wrinkle_intensity: float = 0.0
    translucency: float = 0.0


class OutfitItem(LayerBase):
    slot: str = ""
    name: str = ""
    material: str = ""
    color_hex: str = ""
    condition: str = "worn"
    physical_params: PhysicalParams = Field(default_factory=PhysicalParams)


class Outfit(LayerBase):
    description: str = ""
    ref_images: list[AssetRef | dict[str, Any]] = Field(default_factory=list)
    items: list[OutfitItem | dict[str, Any]] = Field(default_factory=list)


class HairPhysics(LayerBase):
    wind_response: float = 0.0
    gravity_droop: float = 0.0
    wet_clump: float = 0.0


class HairStyle(LayerBase):
    style: str = ""
    color_hex: str = ""
    length_cm: float | None = None
    texture: str = ""
    physics: HairPhysics = Field(default_factory=HairPhysics)


class Makeup(LayerBase):
    type: str = "none"
    intensity: float = 0.0
    regions: list[Any] = Field(default_factory=list)


class Accessory(LayerBase):
    slot: str = ""
    name: str = ""
    description: str = ""
    binding: str = ""


class Skeleton(LayerBase):
    path: str = ""
    format: str = "openpose_18"
    head_ratio: float | None = None
    height_cm: float | None = None
    weight_kg: float | None = None


class PostureDefaults(LayerBase):
    spine_curve: str = ""
    shoulder_state: str = ""
    head_tilt: float = 0.0
    note: str = ""


class BodyMesh(LayerBase):
    path: str = ""
    format: str = "glTF_2.0"
    polycount: int | None = None


class SkinTone(LayerBase):
    base_hex: str = ""
    undertone: str = ""
    freckle_density: float = 0.0
    tan_lines: list[Any] = Field(default_factory=list)


class ActionUnit(LayerBase):
    au: str = ""
    name: str = ""
    intensity: float = 0.0


class ExpressionPreset(LayerBase):
    name: str = ""
    trigger: str = "manual"
    au_set: list[ActionUnit | dict[str, Any]] = Field(default_factory=list)
    duration_hint: str = ""
    note: str = ""


class AuLibrary(LayerBase):
    default_set: list[ActionUnit | dict[str, Any]] = Field(default_factory=list)
    custom_presets: list[ExpressionPreset | dict[str, Any]] = Field(default_factory=list)


class RestingFace(LayerBase):
    brow_position: float = 0.0
    eye_openness: float = 1.0
    gaze_direction: str = ""
    mouth_state: str = ""
    jaw_tension: float = 0.0


class Gaze(LayerBase):
    default_target: str = ""
    tracking_mode: str = "fixed"
    saccade_frequency: float = 0.0
    blink_rate_per_min: float | None = None


class LipSync(LayerBase):
    neutral_mouth_shape: str = "rest_closed"
    openness_range: list[float] = Field(default_factory=lambda: [0.0, 1.0])
    dental_visibility: float = 0.0


class DefaultPose(LayerBase):
    skeleton_path: str = ""
    format: str = "openpose_18"
    description: str = ""


class PoseEntry(LayerBase):
    id: str = ""
    name: str = ""
    skeleton_path: str = ""
    loop: bool = False
    fps: int | None = None
    frames: int | None = None
    note: str = ""


class MovementStyle(LayerBase):
    speed_factor: float = 1.0
    fluidity: float = 0.5
    weight_shift: str = ""
    note: str = ""


class InteractionConstraints(LayerBase):
    personal_space_radius_cm: float | None = None
    touch_aversion: list[str] = Field(default_factory=list)
    note: str = ""


class PhysicsSkin(LayerBase):
    detail_level: float = 0.5
    pore_visibility: float = 0.5
    subsurface_scattering: float = 0.5
    wrinkle_depth: float = 0.5
    elasticity: float = 0.5
    note: str = ""


class PhysicsCloth(LayerBase):
    simulation_mode: str = "auto_by_material"
    wind_sensitivity: float = 0.5
    gravity_response: float = 0.5
    collision_with_body: bool = True
    wrinkle_memory: float = 0.5


class WetBehavior(LayerBase):
    clump_factor: float = 0.0
    darkening: float = 0.0
    weight_increase: float = 0.0


class PhysicsHair(LayerBase):
    simulation_mode: str = "strand_based"
    strand_count_hint: str = "medium"
    static_electricity: float = 0.0
    wet_behavior: WetBehavior = Field(default_factory=WetBehavior)


class FluidSweat(LayerBase):
    enabled: bool = False
    trigger: str = ""
    regions: list[str] = Field(default_factory=list)
    flow_speed: float = 0.0


class FluidTears(LayerBase):
    enabled: bool = False
    trigger: str = ""
    flow_path: str = ""
    volume: str = ""


class FluidBlood(LayerBase):
    enabled: bool = False
    trigger: str = ""
    color_hex: str = "#8B0000"
    viscosity: float = 0.5


class Fluids(LayerBase):
    sweat: FluidSweat = Field(default_factory=FluidSweat)
    tears: FluidTears = Field(default_factory=FluidTears)
    blood: FluidBlood = Field(default_factory=FluidBlood)


class LightingResponse(LayerBase):
    skin_specular: float = 0.3
    eye_reflection: bool = True
    shadow_softness: float = 0.5


class VoiceRef(LayerBase):
    path: str = ""
    duration_sec: float | None = None
    sample_rate: int | None = None
    channels: int | None = None


class VoiceEmbedding(LayerBase):
    path: str = ""
    model: str = ""
    dimension: int = 256


class VoiceCharacteristics(LayerBase):
    pitch: str | float | None = None
    speed_factor: float = 1.0
    breathiness: float = 0.0
    roughness: float = 0.0
    accent: str = ""
    habitual_pause_ms: int | None = None
    note: str = ""


class EncryptionInfo(LayerBase):
    method: str = "AES-256-GCM"
    key_id: str = ""
    iv: str = ""


class EvolutionChange(LayerBase):
    op: Literal["+", "-", "→", "->"] = "+"
    path: str = ""
    value: Any = None


class EvolutionLogEntry(LayerBase):
    scene: int | None = None
    scene_index: int | None = None
    event: str = ""
    changes: list[EvolutionChange | str | dict[str, Any]] | dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    note: str = ""
    permanent: bool | None = None
    heal_scene: int | None = None
    revert_scene: int | None = None
    at: datetime | None = None
    shot_id: str | None = None
    cause: str = ""
    effect: str = ""


class ConditionalConstraint(LayerBase):
    if_: str = Field(default="", alias="if")
    then: str = ""


class QualityFloor(LayerBase):
    face_consistency_min: float = 0.88
    body_proportion_tolerance: float = 0.05
    outfit_color_delta_e_max: float = 4.0


class ComfyUIPlaceholder(LayerBase):
    """僅佔位。核心不執行 Comfy；Q1 禁止 `generate()`。"""

    path: str = ""
    version: str = ""


class ImageGenExtension(LayerBase):
    """第三方生圖引用設定。僅 metadata；核心不呼叫 `generate()`。

    實際呼叫由 CharacterOS `imaging` 服務依 `provider` 路由執行。
    """

    provider: str = ""
    model: str = ""
    endpoint: str = ""
    size: str = "1024x1024"
    last_job_id: str = ""
    last_asset_paths: list[str] = Field(default_factory=list)
    note: str = ""


class MetaLayer(LayerBase):
    format: str = FORMAT_STEM
    format_version: str = FORMAT_VERSION
    charpass_id: str = Field(default_factory=lambda: str(uuid4()))
    character_name: str = ""
    character_alias: list[str] = Field(default_factory=list)
    created_at: datetime | None = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime | None = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = ""
    project_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    thumbnail: str = "thumb/thumb_256.png"
    license: LicenseKind | str = "project_internal"
    checksum: str = ""
    parent_charpass_id: str | None = None
    generation_count: int = 0
    encryption: EncryptionInfo | dict[str, Any] | None = None
    encryption_level: EncryptionLevel | int | str = "L0"
    mode: PackMode = "full"
    size_bytes: int = 0
    parser_version: str = PARSER_VERSION
    entity_id: str = ""
    archived: bool = False


class IdentityLayer(LayerBase):
    ref_images: list[AssetRef | dict[str, Any]] = Field(default_factory=list)
    face_embedding: FaceEmbedding = Field(default_factory=FaceEmbedding)
    ip_adapter: IpAdapter = Field(default_factory=IpAdapter)
    blend: Blend = Field(default_factory=Blend)
    lock_rules: LockRules = Field(default_factory=LockRules)
    name: str = ""
    aliases: list[str] = Field(default_factory=list)
    species: str = "human"
    gender_spectrum: float = 0.5
    age_appearance: str | None = None
    face_id: str | None = None
    face_threshold: float = 0.7
    note: str | None = None
    project_id: str | None = None
    entity_id: str = ""


class BodyLayer(LayerBase):
    template: str = ""
    skeleton: Skeleton = Field(default_factory=Skeleton)
    proportions: dict[str, Any] = Field(default_factory=dict)
    limb_thickness: dict[str, Any] = Field(default_factory=dict)
    posture_defaults: PostureDefaults = Field(default_factory=PostureDefaults)
    mesh: BodyMesh = Field(default_factory=BodyMesh)
    skin_tone: SkinTone = Field(default_factory=SkinTone)
    height_cm: float | None = None
    build: str | None = None
    skin: str | None = None


class VisualStyle(LayerBase):
    """視覺風格：畫風、色調、光影與鏡頭基調。"""

    medium: str = ""
    aesthetic: str = ""
    color_palette: list[str] = Field(default_factory=list)
    lighting: str = ""
    camera: str = ""
    keywords: list[str] = Field(default_factory=list)
    note: str = ""


class ArtPromptStyle(LayerBase):
    """生圖用風格提示詞（正／負向與強度）。"""

    positive: str = ""
    negative: str = ""
    strength: float = 1.0
    template: str = ""
    note: str = ""


class NarrativeStyle(LayerBase):
    """敘事／語氣風格：說話方式與文風。"""

    tone: str = ""
    speech_pattern: str = ""
    diction: str = ""
    register_: str = Field("", alias="register")
    sample_lines: list[str] = Field(default_factory=list)
    note: str = ""


class CharacterStyleProfile(LayerBase):
    """角色風格總覽：視覺、生圖提示、敘事、一致性備註。

    參考圖錨點仍使用 `_style.reference_images` / `_identity.ref_images`
    與 `_style.outfit.ref_images`，不在此重複巢狀。
    """

    visual: VisualStyle = Field(default_factory=VisualStyle)
    art_prompt: ArtPromptStyle = Field(default_factory=ArtPromptStyle)
    narrative: NarrativeStyle = Field(default_factory=NarrativeStyle)
    consistency_notes: str = ""


class StyleLayer(LayerBase):
    outfit: Outfit = Field(default_factory=Outfit)
    hair: HairStyle | str | None = None
    makeup: Makeup = Field(default_factory=Makeup)
    damage_regions: list[DamageRegion | dict[str, Any]] = Field(default_factory=list)
    accessories: list[Accessory | dict[str, Any]] = Field(default_factory=list)
    clothing: list[str] = Field(default_factory=list)
    colors: dict[str, Any] = Field(default_factory=dict)
    ip_adapter_weight: float = 0.7
    reference_images: list[AssetRef | dict[str, Any]] = Field(default_factory=list)
    character_style: CharacterStyleProfile = Field(default_factory=CharacterStyleProfile)
    additional_descriptors: list[str] = Field(default_factory=list)


class ExpressionLayer(LayerBase):
    base_emotion: str = "neutral"
    micro_asymmetry: float = 0.0
    resting_face: RestingFace = Field(default_factory=RestingFace)
    au_library: AuLibrary = Field(default_factory=AuLibrary)
    gaze: Gaze = Field(default_factory=Gaze)
    lip_sync: LipSync = Field(default_factory=LipSync)
    default: str = "neutral"
    range: list[str] = Field(default_factory=list)
    intensity: float = 0.5


class PoseLayer(LayerBase):
    default_pose: DefaultPose = Field(default_factory=DefaultPose)
    pose_library: list[PoseEntry | dict[str, Any]] = Field(default_factory=list)
    movement_style: MovementStyle = Field(default_factory=MovementStyle)
    interaction_constraints: InteractionConstraints = Field(default_factory=InteractionConstraints)
    default: str = "standing"
    head_tilt: float = 0.0
    constraints: list[str] = Field(default_factory=list)


class PhysicsLayer(LayerBase):
    skin: PhysicsSkin = Field(default_factory=PhysicsSkin)
    cloth: PhysicsCloth = Field(default_factory=PhysicsCloth)
    hair: PhysicsHair = Field(default_factory=PhysicsHair)
    fluids: Fluids = Field(default_factory=Fluids)
    lighting_response: LightingResponse = Field(default_factory=LightingResponse)
    mass_kg: float | None = None
    rigidity: float = 0.5
    cloth_sim: bool = False


class VoiceLayer(LayerBase):
    enabled: bool = False
    ref_audio: VoiceRef = Field(default_factory=VoiceRef)
    voice_embedding: VoiceEmbedding = Field(default_factory=VoiceEmbedding)
    characteristics: VoiceCharacteristics = Field(default_factory=VoiceCharacteristics)
    emotional_range: dict[str, Any] = Field(default_factory=dict)
    timbre: str | None = None
    pitch: float | str | None = 0.5
    sample_uri: str | None = None
    language: str = "zh-Hant"
    samples: list[AssetRef | dict[str, Any]] = Field(default_factory=list)


class CausalLayer(LayerBase):
    evolution_log: list[EvolutionLogEntry | dict[str, Any]] = Field(default_factory=list)
    current_state_snapshot: dict[str, Any] = Field(default_factory=dict)


class ConstraintsLayer(LayerBase):
    must_always: list[str] = Field(default_factory=list)
    must_never: list[str] = Field(default_factory=list)
    conditional: list[ConditionalConstraint | dict[str, Any]] = Field(default_factory=list)
    quality_floor: QualityFloor = Field(default_factory=QualityFloor)
    forbidden: list[str] = Field(default_factory=list)
    required: list[str] = Field(default_factory=list)
    continuity: list[str] = Field(default_factory=list)


class ExtensionsLayer(LayerBase):
    comfyui_workflow: ComfyUIPlaceholder = Field(default_factory=ComfyUIPlaceholder)
    comfyui: ComfyUIPlaceholder = Field(default_factory=ComfyUIPlaceholder)
    image_gen: ImageGenExtension = Field(default_factory=ImageGenExtension)


class CharpassManifest(LayerBase):
    """ZIP 內 `manifest.json` 根物件。"""

    schema_uri: str = Field(default=SCHEMA_URI, alias="schema")
    mode: PackMode | None = Field(default=None, alias="_mode")
    asset_base_url: str | None = Field(default=None, alias="_asset_base_url")
    meta: MetaLayer = Field(default_factory=MetaLayer, alias="_meta")
    identity: IdentityLayer = Field(default_factory=IdentityLayer, alias="_identity")
    body: BodyLayer = Field(default_factory=BodyLayer, alias="_body")
    style: StyleLayer = Field(default_factory=StyleLayer, alias="_style")
    expression: ExpressionLayer = Field(default_factory=ExpressionLayer, alias="_expression")
    pose: PoseLayer = Field(default_factory=PoseLayer, alias="_pose")
    physics: PhysicsLayer = Field(default_factory=PhysicsLayer, alias="_physics")
    voice: VoiceLayer = Field(default_factory=VoiceLayer, alias="_voice")
    causal: CausalLayer = Field(default_factory=CausalLayer, alias="_causal")
    constraints: ConstraintsLayer = Field(default_factory=ConstraintsLayer, alias="_constraints")
    extensions: ExtensionsLayer = Field(default_factory=ExtensionsLayer, alias="_extensions")

    @model_validator(mode="after")
    def _sync_aliases(self) -> CharpassManifest:
        sync_layer_aliases(self)
        return self


CharacterPassport = CharpassManifest


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_charpass_id() -> str:
    return str(uuid4())


def charpass_id_short(charpass_id: str) -> str:
    compact = str(charpass_id or "").replace("-", "")
    if compact.lower().startswith("cp"):
        compact = compact[2:]
    return compact[:CHARPASS_ID_SHORT_LEN] if compact else "000000"


def sync_layer_aliases(manifest: CharpassManifest) -> CharpassManifest:
    meta = manifest.meta
    identity = manifest.identity
    style = manifest.style
    constraints = manifest.constraints
    pose = manifest.pose
    body = manifest.body

    if identity.name and not meta.character_name:
        meta.character_name = identity.name
    if meta.character_name and not identity.name:
        identity.name = meta.character_name
    if identity.aliases and not meta.character_alias:
        meta.character_alias = list(identity.aliases)
    if meta.character_alias and not identity.aliases:
        identity.aliases = list(meta.character_alias)
    if identity.project_id and not meta.project_id:
        meta.project_id = identity.project_id
    if meta.project_id and not identity.project_id:
        identity.project_id = meta.project_id
    if identity.entity_id and not meta.entity_id:
        meta.entity_id = identity.entity_id
    if meta.entity_id and not identity.entity_id:
        identity.entity_id = meta.entity_id

    if identity.gender_spectrum != 0.5 and identity.blend.gender_spectrum == 0.5:
        identity.blend.gender_spectrum = identity.gender_spectrum
    elif identity.blend.gender_spectrum != 0.5:
        identity.gender_spectrum = identity.blend.gender_spectrum
    if identity.face_threshold != 0.7 and identity.lock_rules.face_consistency_threshold == 0.88:
        identity.lock_rules.face_consistency_threshold = identity.face_threshold
    elif identity.lock_rules.face_consistency_threshold != 0.88:
        identity.face_threshold = identity.lock_rules.face_consistency_threshold
    if style.ip_adapter_weight != 0.7 and identity.ip_adapter.weight == 0.85:
        identity.ip_adapter.weight = style.ip_adapter_weight
    elif identity.ip_adapter.weight != 0.85:
        style.ip_adapter_weight = identity.ip_adapter.weight

    if not identity.ref_images and style.reference_images:
        identity.ref_images = list(style.reference_images)
    if pose.head_tilt == 0.0 and body.posture_defaults.head_tilt:
        pose.head_tilt = body.posture_defaults.head_tilt
    if body.height_cm is None and body.skeleton.height_cm is not None:
        body.height_cm = body.skeleton.height_cm
    elif body.height_cm is not None and body.skeleton.height_cm is None:
        body.skeleton.height_cm = body.height_cm

    if constraints.required and not constraints.must_always:
        constraints.must_always = list(constraints.required)
    if constraints.must_always and not constraints.required:
        constraints.required = list(constraints.must_always)
    if constraints.forbidden and not constraints.must_never:
        constraints.must_never = list(constraints.forbidden)
    if constraints.must_never and not constraints.forbidden:
        constraints.forbidden = list(constraints.must_never)

    if manifest.mode is None:
        manifest.mode = meta.mode
    else:
        meta.mode = manifest.mode

    if not style.clothing and style.outfit.items:
        names: list[str] = []
        for item in style.outfit.items:
            name = item.name if isinstance(item, OutfitItem) else str(item.get("name") or "")
            if name:
                names.append(name)
        style.clothing = names

    voice = manifest.voice
    if voice.ref_audio.path and not voice.sample_uri:
        voice.sample_uri = voice.ref_audio.path
    if voice.sample_uri and not voice.ref_audio.path:
        voice.ref_audio.path = voice.sample_uri
    if voice.sample_uri or voice.ref_audio.path or voice.samples:
        voice.enabled = True

    causal = manifest.causal
    for entry in causal.evolution_log:
        if not isinstance(entry, EvolutionLogEntry):
            continue
        if entry.scene is None and entry.scene_index is not None:
            entry.scene = entry.scene_index
        if entry.scene_index is None and entry.scene is not None:
            entry.scene_index = entry.scene
        if not entry.event and entry.cause:
            entry.event = entry.cause
        if not entry.cause and entry.event:
            entry.cause = entry.event

    extensions = manifest.extensions
    if extensions.comfyui.path and not extensions.comfyui_workflow.path:
        extensions.comfyui_workflow.path = extensions.comfyui.path
        extensions.comfyui_workflow.version = extensions.comfyui.version
    elif extensions.comfyui_workflow.path and not extensions.comfyui.path:
        extensions.comfyui.path = extensions.comfyui_workflow.path
        extensions.comfyui.version = extensions.comfyui_workflow.version
    return manifest


def empty_manifest_dict() -> dict[str, Any]:
    return CharpassManifest().model_dump(mode="json", by_alias=True)


def parse_manifest(data: dict[str, Any] | CharpassManifest) -> CharpassManifest:
    if isinstance(data, CharpassManifest):
        sync_layer_aliases(data)
        return data
    return CharpassManifest.model_validate(data)


def load_passport(data: dict[str, Any] | CharpassManifest) -> CharpassManifest:
    return parse_manifest(data)


def manifest_to_dict(manifest: CharpassManifest | dict[str, Any]) -> dict[str, Any]:
    parsed = parse_manifest(manifest)
    dumped = parsed.model_dump(mode="json", by_alias=True)
    if isinstance(manifest, dict):
        return _restore_unknown(manifest, dumped)
    extras = getattr(parsed, "__pydantic_extra__", None) or {}
    if extras:
        dumped.update(extras)
    return dumped


def dump_passport(manifest: CharpassManifest | dict[str, Any]) -> dict[str, Any]:
    return manifest_to_dict(manifest)


def _restore_unknown(original: dict[str, Any], dumped: dict[str, Any]) -> dict[str, Any]:
    """Pydantic extra 在巢狀層會保留；此處再把根層未知鍵補回。"""
    merged = dict(dumped)
    for key, value in original.items():
        if key not in merged:
            merged[key] = value
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            for inner_key, inner_val in value.items():
                if inner_key not in merged[key]:
                    merged[key][inner_key] = inner_val
    return merged


def json_schema() -> dict[str, Any]:
    schema = CharpassManifest.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = SCHEMA_URI
    schema["title"] = "Narratron Character Passport"
    schema["description"] = (
        "Narratron Character Passport v1.0（.charpass）。"
        "未知欄位必須原樣保留。核心不讀不改 _extensions。"
    )
    return schema


def dump_json_schema() -> str:
    return json.dumps(json_schema(), ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    from pathlib import Path

    target = Path(__file__).with_name("schema.json")
    target.write_text(dump_json_schema(), encoding="utf-8")
    print(f"wrote {target}")
