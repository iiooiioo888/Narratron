"""Qwen-Image-Edit-2511 LoRA 適配器註冊表與提示詞降維。

對齊上游專案：
https://github.com/PRITHIVSAKTHIUR/Qwen-Image-Edit-2511-LoRAs-Fast-Lazy-Load
"""

from __future__ import annotations

from typing import Any

# 與上游 ADAPTER_SPECS 鍵名一致（懶載入 LoRA 名稱）
ADAPTER_SPECS: dict[str, dict[str, str]] = {
    "Multiple-Angles": {
        "repo": "dx8152/Qwen-Edit-2509-Multiple-angles",
        "weights": "镜头转换.safetensors",
        "adapter_name": "multiple-angles",
        "description": "多角度鏡頭轉換",
    },
    "Photo-to-Anime": {
        "repo": "autoweeb/Qwen-Image-Edit-2509-Photo-to-Anime",
        "weights": "Qwen-Image-Edit-2509-Photo-to-Anime_000001000.safetensors",
        "adapter_name": "photo-to-anime",
        "description": "寫實轉動漫",
    },
    "Anime-V2": {
        "repo": "prithivMLmods/Qwen-Image-Edit-2511-Anime",
        "weights": "Qwen-Image-Edit-2511-Anime-2000.safetensors",
        "adapter_name": "anime-v2",
        "description": "動漫風格 V2（保背景）",
    },
    "Light-Migration": {
        "repo": "dx8152/Qwen-Edit-2509-Light-Migration",
        "weights": "参考色调.safetensors",
        "adapter_name": "light-migration",
        "description": "光照／色調遷移（需兩張圖）",
    },
    "Upscaler": {
        "repo": "starsfriday/Qwen-Image-Edit-2511-Upscale2K",
        "weights": "qwen_image_edit_2511_upscale.safetensors",
        "adapter_name": "upscale-2k",
        "description": "超分至 2K／4K",
    },
    "Style-Transfer": {
        "repo": "zooeyy/Style-Transfer",
        "weights": "Style Transfer-Alpha-V0.1.safetensors",
        "adapter_name": "style-transfer",
        "description": "風格遷移（圖1→圖2風格）",
    },
    "Manga-Tone": {
        "repo": "nappa114514/Qwen-Image-Edit-2509-Manga-Tone",
        "weights": "tone001.safetensors",
        "adapter_name": "manga-tone",
        "description": "漫畫網點色調",
    },
    "Anything2Real": {
        "repo": "lrzjason/Anything2Real_2601",
        "weights": "anything2real_2601.safetensors",
        "adapter_name": "anything2real",
        "description": "任意風格轉寫實",
    },
    "Fal-Multiple-Angles": {
        "repo": "fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA",
        "weights": "qwen-image-edit-2511-multiple-angles-lora.safetensors",
        "adapter_name": "fal-multiple-angles",
        "description": "多角度（Fal 版）",
    },
    "Polaroid-Photo": {
        "repo": "prithivMLmods/Qwen-Image-Edit-2511-Polaroid-Photo",
        "weights": "Qwen-Image-Edit-2511-Polaroid-Photo.safetensors",
        "adapter_name": "polaroid-photo",
        "description": "拍立得質感",
    },
    "Unblur-Anything": {
        "repo": "prithivMLmods/Qwen-Image-Edit-2511-Unblur-Upscale",
        "weights": "Qwen-Image-Edit-Unblur-Upscale_15.safetensors",
        "adapter_name": "unblur-anything",
        "description": "去模糊並超分",
    },
    "Midnight-Noir-Eyes-Spotlight": {
        "repo": "prithivMLmods/Qwen-Image-Edit-2511-Midnight-Noir-Eyes-Spotlight",
        "weights": "Qwen-Image-Edit-2511-Midnight-Noir-Eyes-Spotlight.safetensors",
        "adapter_name": "midnight-noir-eyes-spotlight",
        "description": "午夜黑色調眼神聚光",
    },
    "Hyper-Realistic-Portrait": {
        "repo": "prithivMLmods/Qwen-Image-Edit-2511-Hyper-Realistic-Portrait",
        "weights": "HRP_20.safetensors",
        "adapter_name": "hyper-realistic-portrait",
        "description": "超寫實肖像",
    },
    "Ultra-Realistic-Portrait": {
        "repo": "prithivMLmods/Qwen-Image-Edit-2511-Ultra-Realistic-Portrait",
        "weights": "URP_20.safetensors",
        "adapter_name": "ultra-realistic-portrait",
        "description": "極致寫實肖像",
    },
    "Pixar-Inspired-3D": {
        "repo": "prithivMLmods/Qwen-Image-Edit-2511-Pixar-Inspired-3D",
        "weights": "PI3_20.safetensors",
        "adapter_name": "pi3",
        "description": "皮克斯風 3D",
    },
    "Noir-Comic-Book": {
        "repo": "prithivMLmods/Qwen-Image-Edit-2511-Noir-Comic-Book-Panel",
        "weights": "Noir-Comic-Book-Panel_20.safetensors",
        "adapter_name": "ncb",
        "description": "黑色漫畫分鏡風",
    },
    "Any-light": {
        "repo": "lilylilith/QIE-2511-MP-AnyLight",
        "weights": "QIE-2511-AnyLight_.safetensors",
        "adapter_name": "any-light",
        "description": "任意光照遷移（需兩張圖）",
    },
    "Studio-DeLight": {
        "repo": "prithivMLmods/QIE-2511-Studio-DeLight",
        "weights": "QIE-2511-Studio-DeLight-5000.safetensors",
        "adapter_name": "studio-delight",
        "description": "影棚均勻去陰影",
    },
    "Cinematic-FlatLog": {
        "repo": "prithivMLmods/QIE-2511-Cinematic-FlatLog-Control",
        "weights": "QIE-2511-Cinematic-FlatLog-Control-3200.safetensors",
        "adapter_name": "flat-log",
        "description": "電影 Flat Log 調色",
    },
}

DEFAULT_LORA = "Photo-to-Anime"
DEFAULT_STEPS = 4
DEFAULT_GUIDANCE = 1.0
QWEN_EDIT_MAX_REF_IMAGES = 2

# CharacterOS 視角 → Multiple-Angles / Fal 編輯提示
ANGLE_EDIT_PROMPTS: dict[str, str] = {
    "front": "Front view of the same character. Keep identity, outfit, and proportions unchanged.",
    "three_quarter": "Front-right three-quarter view of the same character. Preserve identity.",
    "left": "Rotate the camera 90 degrees to the left for a left profile. Preserve identity.",
    "right": "Rotate the camera 90 degrees to the right for a right profile. Preserve identity.",
    "back": "Rotate the camera 180 degrees for a back view. Preserve identity and outfit.",
    "top": "Slight high-angle top-down view of the same character. Preserve identity.",
    "bottom": "Slight low-angle upward view of the same character. Preserve identity.",
    "face_detail": "Tight face close-up portrait of the same character. Preserve facial identity.",
    "tpose": "Same character standing in a neutral T-pose, full body. Preserve identity and outfit.",
}

# 風格關鍵字 → LoRA（敘事自舉「可愛／吉卜力／公主風」等降維）
STYLE_LORA_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("pixar", "3d", "cgi", "皮克斯"), "Pixar-Inspired-3D"),
    (("manga", "漫畫", "網點"), "Manga-Tone"),
    (("noir", "comic", "黑色漫畫"), "Noir-Comic-Book"),
    (("anime", "動漫", "吉卜力", "ghibli", "可愛", "二次元"), "Anime-V2"),
    (("cartoon", "卡通"), "Photo-to-Anime"),
    (("polaroid", "拍立得"), "Polaroid-Photo"),
    (("flatlog", "flat log", "log"), "Cinematic-FlatLog"),
    (("hyper", "超寫實"), "Hyper-Realistic-Portrait"),
    (("ultra", "極致寫實"), "Ultra-Realistic-Portrait"),
    (("real", "寫實", "photo", "realistic", "真人"), "Anything2Real"),
    (("studio", "影棚", "delight"), "Studio-DeLight"),
]


def list_loras() -> list[dict[str, str]]:
    return [
        {
            "name": name,
            "adapter_name": spec["adapter_name"],
            "description": spec.get("description") or "",
            "repo": spec.get("repo") or "",
        }
        for name, spec in ADAPTER_SPECS.items()
    ]


def normalize_lora(name: str | None) -> str:
    cleaned = str(name or "").strip()
    if cleaned in ADAPTER_SPECS:
        return cleaned
    lowered = cleaned.lower()
    for key in ADAPTER_SPECS:
        if key.lower() == lowered:
            return key
        adapter = ADAPTER_SPECS[key].get("adapter_name", "")
        if adapter.lower() == lowered:
            return key
    return DEFAULT_LORA


def resolve_angle_prompt(angle: str | None, fallback_prompt: str = "") -> str:
    key = str(angle or "").strip().lower()
    if key in ANGLE_EDIT_PROMPTS:
        return ANGLE_EDIT_PROMPTS[key]
    text = str(fallback_prompt or "").strip()
    return text or ANGLE_EDIT_PROMPTS["front"]


def infer_style_lora(*texts: Any) -> str | None:
    blob = " ".join(str(item or "") for item in texts).lower()
    if not blob.strip():
        return None
    for keywords, lora in STYLE_LORA_HINTS:
        if any(token.lower() in blob for token in keywords):
            return lora
    return None


def pick_lora_for_request(
    *,
    purpose: str = "identity",
    angle: str | None = None,
    explicit_lora: str | None = None,
    style_hints: str = "",
    multi_angle: bool = False,
) -> str:
    if explicit_lora and str(explicit_lora).strip():
        return normalize_lora(explicit_lora)

    purpose_key = str(purpose or "").strip().lower()
    angle_key = str(angle or "").strip().lower()

    if purpose_key in {"thumb"} or "upscale" in purpose_key:
        return "Upscaler"
    if purpose_key in {"relight", "lighting"}:
        return "Studio-DeLight"

    if multi_angle or angle_key in ANGLE_EDIT_PROMPTS:
        return "Multiple-Angles"

    style_lora = infer_style_lora(style_hints, purpose_key)
    if style_lora:
        return style_lora

    return DEFAULT_LORA


def build_edit_prompt(
    *,
    prompt: str,
    angle: str | None = None,
    lora: str | None = None,
    multi_angle: bool = False,
) -> str:
    """依 LoRA／視角組出給 Qwen Edit 的指令；保身份一致性。"""
    resolved_lora = normalize_lora(lora)
    base = str(prompt or "").strip()
    angle_key = str(angle or "").strip().lower()

    if resolved_lora in {"Multiple-Angles", "Fal-Multiple-Angles"} or (
        multi_angle and angle_key in ANGLE_EDIT_PROMPTS
    ):
        angled = resolve_angle_prompt(angle_key, base)
        return (
            f"{angled} "
            "Preserve the exact same character identity, face, hair, outfit, and proportions. "
            "Exactly one character in frame."
        ).strip()

    if resolved_lora == "Upscaler":
        return base or "Upscale this picture to 4K resolution. Preserve identity and details."
    if resolved_lora == "Unblur-Anything":
        return base or "Unblur and upscale. Preserve identity and details."
    if resolved_lora == "Studio-DeLight":
        return base or "Neutral uniform lighting. Preserve identity and composition."
    if resolved_lora == "Photo-to-Anime":
        return base or "Transform into anime while preserving character identity."
    if resolved_lora == "Anime-V2":
        return (
            base
            or "Transform into anime while preserving the background and remaining elements, "
            "maintaining realism of original details and character identity."
        )
    if resolved_lora == "Pixar-Inspired-3D":
        return base or "Transform it into Pixar-inspired 3D. Preserve character identity."
    if resolved_lora == "Manga-Tone":
        return base or "Paint with manga tone. Preserve character identity."
    if resolved_lora == "Noir-Comic-Book":
        return base or "Transform into a noir comic book style. Preserve character identity."
    if resolved_lora == "Anything2Real":
        return base or "Change the picture to realistic photograph. Preserve character identity."
    if resolved_lora == "Hyper-Realistic-Portrait":
        return base or "Transform into a hyper-realistic face portrait. Preserve identity."
    if resolved_lora == "Ultra-Realistic-Portrait":
        return base or "Ultra-realistic portrait. Preserve identity."
    if resolved_lora == "Cinematic-FlatLog":
        return base or "Transform into a cinematic flat log. Preserve identity."
    if resolved_lora == "Polaroid-Photo":
        return (
            base
            or "cinematic polaroid with soft grain subtle vignette gentle lighting white frame "
            "handwritten photographed preserving realistic texture and details."
        )
    if resolved_lora == "Midnight-Noir-Eyes-Spotlight":
        return base or "Transform into Midnight Noir Eyes Spotlight. Preserve identity."

    if not base:
        return "Edit the image while preserving character identity. Exactly one character in frame."
    return f"{base} Preserve character identity. Exactly one character in frame."
