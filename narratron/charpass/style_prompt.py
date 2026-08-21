"""從 `_style.character_style` 組裝生圖／敘事提示詞。不呼叫任何模型 API。"""

from __future__ import annotations

from typing import Any

from narratron.charpass.schema import parse_manifest


PURPOSE_SLOTS: dict[str, dict[str, str]] = {
    "identity": {
        "shot": "single character turnaround reference, one person only, one subject per image, face clearly visible, neutral expression, model sheet consistency, same character identity across all turnaround angles",
        "asset_dir": "assets/identity",
        "filename_prefix": "ref_face",
    },
    "face_detail": {
        "shot": "single character extreme facial close-up, one face only, one subject per image, straight-on face crop, highly detailed eyes skin nose lips and facial structure, neutral expression, same identity as the turnaround reference",
        "asset_dir": "assets/face_detail",
        "filename_prefix": "ref_face_face_detail",
    },
    "outfit": {
        "shot": "full-body standing, outfit clearly visible, studio lighting",
        "asset_dir": "assets/style",
        "filename_prefix": "outfit_ref",
    },
    "expression": {
        "shot": "close-up face, expression readable, consistent identity",
        "asset_dir": "assets/expression",
        "filename_prefix": "expr",
    },
    "thumb": {
        "shot": "character thumbnail, centered, clean background",
        "asset_dir": "thumb",
        "filename_prefix": "thumb",
    },
    "tpose": {
        "shot": "single character full-body T-pose standing reference, one person only, T-pose, arms stretched straight out horizontally at shoulder height, palms facing down, legs straight, facing camera, 3D character model sheet, T型體, same identity as the face-detail reference",
        "asset_dir": "assets/tpose",
        "filename_prefix": "ref_tpose",
    },
}

# 生圖預設多視角：正／背／左／右／四分之三／頂／底，維持同一角色造型。
MULTI_VIEW_ANGLES: list[dict[str, str]] = [
    {
        "key": "front",
        "label": "front view",
        "shot": "front view, facing camera directly, full body, neutral standing pose, arms relaxed at sides",
    },
    {
        "key": "back",
        "label": "back view",
        "shot": "back view, facing away from camera, full body, neutral standing pose",
    },
    {
        "key": "left",
        "label": "left side view",
        "shot": "left side profile, 90-degree angle, profile view, full body, neutral standing pose",
    },
    {
        "key": "right",
        "label": "right side view",
        "shot": "right side profile, 90-degree angle, profile view, full body, neutral standing pose",
    },
    {
        "key": "three_quarter",
        "label": "three-quarter view",
        "shot": "three-quarter view, 45-degree angle, full body, neutral standing pose",
    },
    {
        "key": "top",
        "label": "top view",
        "shot": "top-down view from above, full body, neutral standing pose, body silhouette clearly readable",
    },
    {
        "key": "bottom",
        "label": "bottom view",
        "shot": "bottom-up view from below, full body, neutral standing pose, body silhouette clearly readable",
    },
]

IDENTITY_SUPPLEMENTAL_ANGLES: list[dict[str, str]] = [
    {
        "key": "face_detail",
        "label": "face detail",
        "shot": "single character extreme facial close-up, one face only, straight-on face crop, highly detailed eyes skin nose lips and facial structure, neutral expression, same identity as the turnaround reference",
    }
]

TPOSE_ANGLES: list[dict[str, str]] = [
    {
        "key": "tpose",
        "label": "T-pose front view",
        "shot": "full-body T-pose standing reference, T-pose, arms stretched straight out horizontally at shoulder height, palms facing down, legs straight together, facing camera, 3D character model sheet, T型體",
    }
]

# prompt 用的 layout 描述文字（給第三方生圖模型參考）
MULTI_VIEW_BASE = (
    "single character only, one person only, full body isolated subject, "
    "each image contains exactly one character, "
    "consistent identity outfit hair and body proportions, "
    "clean neutral studio background, even soft lighting, model sheet quality, "
    "no text labels, no duplicate figure, no collage"
)

MULTI_VIEW_NEGATIVE = (
    "inconsistent design, different character, wrong angle, cropped body, "
    "cut off limbs, duplicate poses, blurry, low quality, watermark, text overlay, "
    "multiple characters, collage errors, deformed face, asymmetric eyes, broken facial features"
)

SINGLE_CHARACTER_GUARD = (
    "single character only, one person only, no extra people, no duplicate body, no second face"
)

IDENTITY_LOCK_GUARD = (
    "preserve the same character identity across every image, same face, same hairstyle, same body proportions, same outfit language"
)

FACE_DETAIL_LOCK_GUARD = (
    "same character identity as the turnaround references, preserve exact face shape, eyes, eyebrows, nose, lips, "
    "skin texture, hairline and facial proportions, facial landmarks and micro details clearly readable, "
    "no hands covering face, no accessories blocking facial features"
)

TPOSE_LOCK_GUARD = (
    "same character identity as the face-detail references, preserve exact face, hair silhouette, skin tone, "
    "body proportions and outfit language, full body visible, T-pose only, no action pose, no sitting, no cropped limbs"
)

IDENTITY_ANGLE_LOCK_GUARD = (
    "render this angle as the same single subject from the identity turnaround set, preserve the exact same face, "
    "hair silhouette, skin tone, outfit design cues and body proportions, keep exactly one character in frame"
)

DEFAULT_SINGLE_ANGLE_BY_PURPOSE: dict[str, str] = {
    "identity": "front",
    "face_detail": "face_detail",
    "outfit": "front",
    "expression": "front",
    "thumb": "front",
    "tpose": "tpose",
}

# ============================================
# CharacterOS 預設風格（缺省補齊用）
# ============================================
# 用於當 profile.manifest 缺少 `_style.character_style.visual.*` 時，
# 仍能生成帶有「3D建模風格／T 型體」特徵的 prompt。
DEFAULT_CHARACTER_STYLE_PRESET = "3D建模風格, T型體"
DEFAULT_STYLE_MEDIUM = "3D建模風格"
DEFAULT_STYLE_AESTHETIC = "T型體"
DEFAULT_CREATED_BY = DEFAULT_CHARACTER_STYLE_PRESET


def _parse_style_preset(value: Any) -> tuple[str, str]:
    raw = str(value or "").replace("，", ",").strip()
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    medium = parts[0] if parts else ""
    aesthetic = ", ".join(parts[1:]) if len(parts) > 1 else ""
    return medium, aesthetic


def apply_default_character_style(manifest: dict[str, Any]) -> dict[str, Any]:
    """
    補齊缺省的角色視覺風格欄位。

    不呼叫任何外部模型；僅就地修改 manifest dict，供 CharacterOS imaging 組 prompt 使用。
    """

    if not isinstance(manifest, dict):
        return {}

    meta = manifest.setdefault("_meta", {})
    if isinstance(meta, dict) and not meta.get("created_by"):
        meta["created_by"] = DEFAULT_CREATED_BY

    style = manifest.setdefault("_style", {})
    if not isinstance(style, dict):
        style = {}
        manifest["_style"] = style

    character_style = style.setdefault("character_style", {})
    if not isinstance(character_style, dict):
        character_style = {}
        style["character_style"] = character_style

    visual = character_style.setdefault("visual", {})
    if not isinstance(visual, dict):
        visual = {}
        character_style["visual"] = visual

    if not visual.get("medium"):
        visual["medium"] = ""
    if not visual.get("aesthetic"):
        visual["aesthetic"] = ""

    derived_medium = ""
    derived_aesthetic = ""
    if isinstance(meta, dict):
        derived_medium, derived_aesthetic = _parse_style_preset(meta.get("created_by"))
    if not derived_medium and character_style.get("preset"):
        derived_medium, derived_aesthetic = _parse_style_preset(character_style.get("preset"))

    if not visual.get("medium"):
        visual["medium"] = derived_medium or DEFAULT_STYLE_MEDIUM
    if not visual.get("aesthetic"):
        visual["aesthetic"] = derived_aesthetic or DEFAULT_STYLE_AESTHETIC

    return manifest

ANGLE_BY_KEY: dict[str, dict[str, str]] = {item["key"]: item for item in MULTI_VIEW_ANGLES}
ANGLE_BY_KEY.update({item["key"]: item for item in IDENTITY_SUPPLEMENTAL_ANGLES})
ANGLE_BY_KEY.update({item["key"]: item for item in TPOSE_ANGLES})


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return {}


def character_style_dict(manifest: dict[str, Any] | Any) -> dict[str, Any]:
    parsed = parse_manifest(manifest)
    style = _as_dict(parsed.style)
    profile = style.get("character_style") or {}
    return profile if isinstance(profile, dict) else {}


def collect_ref_image_uris(manifest: dict[str, Any] | Any) -> list[str]:
    """收集身份／妝造／風格參考圖 URI，供第三方 API 當 consistency 錨點。"""

    parsed = parse_manifest(manifest)
    uris: list[str] = []
    seen: set[str] = set()

    def _push(items: Any) -> None:
        for item in items or []:
            if not isinstance(item, dict):
                dump = getattr(item, "model_dump", None)
                item = dump(mode="json") if callable(dump) else {}
            uri = str(item.get("uri") or item.get("path") or "").strip()
            if uri and uri not in seen:
                seen.add(uri)
                uris.append(uri)

    identity = _as_dict(parsed.identity)
    style = _as_dict(parsed.style)
    outfit = style.get("outfit") if isinstance(style.get("outfit"), dict) else {}
    _push(identity.get("ref_images"))
    _push(style.get("reference_images"))
    _push(outfit.get("ref_images"))
    return uris


def _merge_negative_prompt(base: str, *extra_parts: str) -> str:
    chunks: list[str] = []
    seen: set[str] = set()
    for part in (base, *extra_parts):
        for item in str(part or "").split(","):
            cleaned = item.strip()
            if cleaned and cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                chunks.append(cleaned)
    return ", ".join(chunks)


def _extend_unique(parts: list[str], *values: str) -> None:
    seen = {item.strip().lower() for item in parts if item.strip()}
    for value in values:
        cleaned = str(value or "").strip().rstrip(",")
        if cleaned and cleaned.lower() not in seen:
            parts.append(cleaned)
            seen.add(cleaned.lower())


def _normalize_prompt_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _humanize_key(key: str) -> str:
    return str(key or "").replace("_", " ").strip()


def _append_freeform_fields(parts: list[str], payload: dict[str, Any], *, skip: set[str]) -> None:
    for key, value in payload.items():
        if key in skip:
            continue
        label = _humanize_key(key)
        if isinstance(value, list):
            items = _normalize_prompt_list(value)
            if items:
                _extend_unique(parts, f"{label}: {', '.join(items)}")
            continue
        if isinstance(value, dict):
            nested_items = [
                f"{_humanize_key(inner_key)}: {inner_value}"
                for inner_key, inner_value in value.items()
                if str(inner_value or "").strip()
            ]
            if nested_items:
                _extend_unique(parts, f"{label}: {', '.join(nested_items)}")
            continue
        cleaned = str(value or "").strip()
        if cleaned:
            _extend_unique(parts, f"{label}: {cleaned}")


def default_single_angle_for_purpose(purpose: str) -> str:
    return DEFAULT_SINGLE_ANGLE_BY_PURPOSE.get(str(purpose or "").strip(), "")


def resolve_prompt_angle(*, purpose: str, angle: str | None = None, multi_angle: bool = True) -> str:
    explicit = str(angle or "").strip()
    if explicit:
        return explicit
    if str(purpose or "").strip() == "face_detail":
        return "face_detail"
    if str(purpose or "").strip() == "tpose":
        return "tpose"
    if not multi_angle:
        return default_single_angle_for_purpose(purpose)
    return ""


def _append_style_prompt_parts(
    parts: list[str],
    *,
    visual: dict[str, Any],
    outfit: dict[str, Any],
    hair_dict: dict[str, Any],
    style: dict[str, Any],
    art: dict[str, Any],
    consistency_notes: str,
    name: str,
    prompt_purpose: str,
) -> None:
    if visual.get("medium"):
        _extend_unique(parts, str(visual["medium"]))
    if visual.get("aesthetic"):
        _extend_unique(parts, str(visual["aesthetic"]))
    if visual.get("lighting"):
        _extend_unique(parts, str(visual["lighting"]))
    if visual.get("camera"):
        _extend_unique(parts, str(visual["camera"]))
    if visual.get("note"):
        _extend_unique(parts, str(visual["note"]))
    keywords = _normalize_prompt_list(visual.get("keywords"))
    if keywords:
        _extend_unique(parts, *keywords)
    palette = _normalize_prompt_list(visual.get("color_palette"))
    if palette:
        _extend_unique(parts, "color palette: " + ", ".join(palette))
    _append_freeform_fields(
        parts,
        visual,
        skip={"medium", "aesthetic", "lighting", "camera", "note", "keywords", "color_palette"},
    )
    if outfit.get("description"):
        _extend_unique(parts, "outfit: " + str(outfit["description"]))
    if hair_dict.get("style"):
        _extend_unique(parts, "hair: " + str(hair_dict["style"]))
    descriptors = _normalize_prompt_list(style.get("additional_descriptors"))
    if descriptors:
        _extend_unique(parts, *descriptors)
    template = str(art.get("template") or "").strip()
    if template:
        _extend_unique(parts, template.replace("{name}", name).replace("{purpose}", prompt_purpose))
    if art.get("positive"):
        _extend_unique(parts, str(art["positive"]))
    if art.get("note"):
        _extend_unique(parts, str(art["note"]))
    _append_freeform_fields(
        parts,
        art,
        skip={"template", "positive", "negative", "strength", "note"},
    )
    if consistency_notes:
        _extend_unique(parts, "consistency notes: " + consistency_notes)


def _append_evolution_prompt_parts(parts: list[str], manifest: dict[str, Any]) -> None:
    """把演化層（情緒／場景／天氣／傷痕）寫進生圖 prompt，而不只是存在 metadata。"""
    data = manifest if isinstance(manifest, dict) else {}
    expression = data.get("_expression") if isinstance(data.get("_expression"), dict) else {}
    emotion = str(expression.get("base_emotion") or "").strip()
    if emotion and emotion.lower() != "neutral":
        _extend_unique(parts, f"expression: {emotion}")
    micros = expression.get("micro_expressions")
    if isinstance(micros, list):
        labels = [str(item).replace("_", " ").strip() for item in micros if str(item or "").strip()]
        if labels:
            _extend_unique(parts, ", ".join(labels))

    weather = data.get("_weather") if isinstance(data.get("_weather"), dict) else {}
    effects = weather.get("effects") if isinstance(weather.get("effects"), dict) else {}
    if effects.get("prompt"):
        _extend_unique(parts, str(effects["prompt"]))
    else:
        condition = str(weather.get("condition") or "").strip()
        if condition:
            _extend_unique(parts, f"weather: {condition}")

    scene = data.get("_scene_context") if isinstance(data.get("_scene_context"), dict) else {}
    scene_type = str(scene.get("scene_type") or "").strip()
    env = scene.get("environmental_effects") if isinstance(scene.get("environmental_effects"), dict) else {}
    if scene_type:
        _extend_unique(parts, f"scene: {scene_type}")
    if env.get("prompt"):
        _extend_unique(parts, str(env["prompt"]))
    damage = str(env.get("outfit_damage") or "").strip()
    if damage and damage not in {"none", "0"}:
        _extend_unique(parts, f"clothing damage: {damage.replace('_', ' ')}")

    body = data.get("_body") if isinstance(data.get("_body"), dict) else {}
    marks = body.get("injury_marks")
    if isinstance(marks, list):
        readable = [str(item).replace("_", " ").strip() for item in marks if str(item or "").strip()]
        if readable:
            _extend_unique(parts, "visible injuries: " + ", ".join(readable))


def _effective_prompt_purpose(*, purpose: str, effective_angle: str) -> str:
    if effective_angle == "face_detail":
        return "face_detail"
    return purpose


def _append_angle_prompt_parts(
    parts: list[str],
    *,
    slot: dict[str, str],
    effective_angle: str,
    purpose: str,
    multi_angle: bool,
) -> None:
    angle_def = ANGLE_BY_KEY.get(effective_angle)
    is_face_detail = purpose == "face_detail" or effective_angle == "face_detail"
    is_tpose = purpose == "tpose" or effective_angle == "tpose"
    prompt_slot = PURPOSE_SLOTS["face_detail"] if is_face_detail else PURPOSE_SLOTS["tpose"] if is_tpose else slot
    if angle_def:
        # 保留可前向相容的「角度 label」字串（例如 `left side view`），
        # 以避免只有 `shot` 而導致測試/上游解析依賴字串時失配。
        label = str(angle_def.get("label") or "").strip()
        if label:
            _extend_unique(parts, label)
        _extend_unique(parts, prompt_slot["shot"], angle_def["shot"])
    else:
        _extend_unique(parts, prompt_slot["shot"])

    if is_face_detail:
        _extend_unique(
            parts,
            SINGLE_CHARACTER_GUARD,
            "one face only, one head only, no split-screen, no collage, no multi-panel composition",
            "close-up portrait of only the same single character, not a lineup, not a contact sheet, not multiple crops",
            "use the same person as all identity reference images, preserve ethnicity, age appearance, skin tone and facial structure",
            "the face must match the same character from the identity turnaround set, no redesign, no face variation, no alternate person",
            "keep the same visual style rendering, medium, aesthetic treatment, lighting language and material response as the character style profile",
            IDENTITY_LOCK_GUARD,
            FACE_DETAIL_LOCK_GUARD,
            IDENTITY_ANGLE_LOCK_GUARD,
        )
        return

    if is_tpose:
        _extend_unique(
            parts,
            SINGLE_CHARACTER_GUARD,
            "exactly one character, one T-pose, one camera angle, no crowd, no partner, no background character",
            "keep the same named character, same rendering style, same visual medium, same aesthetic treatment and same design language",
            IDENTITY_LOCK_GUARD,
            TPOSE_LOCK_GUARD,
            IDENTITY_ANGLE_LOCK_GUARD,
            MULTI_VIEW_BASE,
        )
        return

    _extend_unique(
        parts,
        SINGLE_CHARACTER_GUARD,
        "exactly one character, one pose, one camera angle, no crowd, no partner, no background character",
        "keep the same named character, same rendering style, same visual medium, same aesthetic treatment and same design language",
        IDENTITY_LOCK_GUARD,
        IDENTITY_ANGLE_LOCK_GUARD,
    )
    if multi_angle or angle_def:
        _extend_unique(parts, MULTI_VIEW_BASE)
    else:
        _extend_unique(parts, "full body reference render, same identity, no extra people, no collage")


def build_image_prompt(
    manifest: dict[str, Any] | Any,
    *,
    purpose: str = "identity",
    extra: str = "",
    angle: str | None = None,
    multi_angle: bool = True,
) -> dict[str, str]:
    """組裝第三方生圖用的正／負向提示詞。

    Returns:
        ``{"positive", "negative", "purpose"}``
    """

    normalized_manifest = apply_default_character_style(_as_dict(manifest) or {})
    parsed = parse_manifest(normalized_manifest)
    meta = _as_dict(parsed.meta)
    identity = _as_dict(parsed.identity)
    style = _as_dict(parsed.style)
    profile = style.get("character_style") if isinstance(style.get("character_style"), dict) else {}
    visual = profile.get("visual") if isinstance(profile.get("visual"), dict) else {}
    art = profile.get("art_prompt") if isinstance(profile.get("art_prompt"), dict) else {}
    outfit = style.get("outfit") if isinstance(style.get("outfit"), dict) else {}
    hair = style.get("hair")
    hair_dict = hair if isinstance(hair, dict) else {"style": str(hair or "")}
    consistency_notes = str(profile.get("consistency_notes") or "").strip()

    slot = PURPOSE_SLOTS.get(purpose, PURPOSE_SLOTS["identity"])
    name = str(identity.get("name") or meta.get("character_name") or "character")
    age_visual = identity.get("age_visual")
    blend = identity.get("blend") if isinstance(identity.get("blend"), dict) else {}
    if age_visual in (None, ""):
        age_visual = blend.get("age_visual")
    age_appearance = identity.get("age_appearance")
    species = identity.get("species") or "human"
    effective_angle = resolve_prompt_angle(purpose=purpose, angle=angle, multi_angle=multi_angle)
    prompt_purpose = _effective_prompt_purpose(purpose=purpose, effective_angle=effective_angle)

    parts: list[str] = [f"{name}, {species}"]
    if age_visual not in (None, ""):
        _extend_unique(parts, f"exactly {age_visual} years old", f"age {age_visual}")
    elif age_appearance:
        _extend_unique(parts, str(age_appearance))
    _append_style_prompt_parts(
        parts,
        visual=visual,
        outfit=outfit,
        hair_dict=hair_dict,
        style=style,
        art=art,
        consistency_notes=consistency_notes,
        name=name,
        prompt_purpose=prompt_purpose,
    )
    _append_evolution_prompt_parts(parts, normalized_manifest)
    _append_angle_prompt_parts(
        parts,
        slot=slot,
        effective_angle=effective_angle,
        purpose=purpose,
        multi_angle=multi_angle,
    )
    if extra:
        _extend_unique(parts, extra.strip())

    positive = ", ".join(part.strip().rstrip(",") for part in parts if str(part).strip())
    negative = _merge_negative_prompt(
        str(art.get("negative") or "").strip(),
        MULTI_VIEW_NEGATIVE if multi_angle else "",
        "multiple characters, extra person, duplicate figure, identity drift, different face, face swap",
        "split face, double head, extra limbs",
        "two people, group shot, lineup, contact sheet, diptych, triptych, mirrored subject",
        "identity mismatch, alternate hairstyle, alternate costume, inconsistent facial structure",
    )
    return {
        "positive": positive,
        "negative": negative,
        "purpose": purpose,
        "angle": effective_angle,
        "multi_angle": multi_angle,
    }


def build_narrative_prompt(manifest: dict[str, Any] | Any) -> str:
    """組裝敘事／對白語氣提示（給文字模型，非生圖）。"""

    parsed = parse_manifest(manifest)
    identity = _as_dict(parsed.identity)
    meta = _as_dict(parsed.meta)
    style = _as_dict(parsed.style)
    profile = style.get("character_style") if isinstance(style.get("character_style"), dict) else {}
    narrative = profile.get("narrative") if isinstance(profile.get("narrative"), dict) else {}
    name = str(identity.get("name") or meta.get("character_name") or "角色")
    chunks = [f"以 {name} 的口吻書寫。"]
    if narrative.get("tone"):
        chunks.append(f"語氣：{narrative['tone']}。")
    if narrative.get("register"):
        chunks.append(f"語域：{narrative['register']}。")
    if narrative.get("diction"):
        chunks.append(f"用詞：{narrative['diction']}。")
    if narrative.get("speech_pattern"):
        chunks.append(f"說話方式：{narrative['speech_pattern']}。")
    samples = narrative.get("sample_lines") or []
    if isinstance(samples, list) and samples:
        quoted = " / ".join(f"「{line}」" for line in samples if line)
        chunks.append(f"參考對白：{quoted}")
    if narrative.get("note"):
        chunks.append(str(narrative["note"]))
    return "".join(chunks)
