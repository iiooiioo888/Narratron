"""從 `_style.character_style` 組裝生圖／敘事提示詞。不呼叫任何模型 API。"""

from __future__ import annotations

from typing import Any

from narratron.charpass.schema import parse_manifest


PURPOSE_SLOTS: dict[str, dict[str, str]] = {
    "identity": {
        "shot": "head-and-shoulders portrait, face clearly visible, neutral expression",
        "asset_dir": "assets/identity",
        "filename_prefix": "ref_face",
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
}


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


def build_image_prompt(
    manifest: dict[str, Any] | Any,
    *,
    purpose: str = "identity",
    extra: str = "",
) -> dict[str, str]:
    """組裝第三方生圖用的正／負向提示詞。

    Returns:
        ``{"positive", "negative", "purpose"}``
    """

    parsed = parse_manifest(manifest)
    meta = _as_dict(parsed.meta)
    identity = _as_dict(parsed.identity)
    style = _as_dict(parsed.style)
    profile = style.get("character_style") if isinstance(style.get("character_style"), dict) else {}
    visual = profile.get("visual") if isinstance(profile.get("visual"), dict) else {}
    art = profile.get("art_prompt") if isinstance(profile.get("art_prompt"), dict) else {}
    outfit = style.get("outfit") if isinstance(style.get("outfit"), dict) else {}
    hair = style.get("hair")
    hair_dict = hair if isinstance(hair, dict) else {"style": str(hair or "")}

    slot = PURPOSE_SLOTS.get(purpose, PURPOSE_SLOTS["identity"])
    name = str(identity.get("name") or meta.get("character_name") or "character")
    age = identity.get("age_appearance")
    species = identity.get("species") or "human"

    parts: list[str] = [f"{name}, {species}"]
    if age:
        parts.append(str(age))
    if visual.get("medium"):
        parts.append(str(visual["medium"]))
    if visual.get("aesthetic"):
        parts.append(str(visual["aesthetic"]))
    if visual.get("lighting"):
        parts.append(str(visual["lighting"]))
    if visual.get("camera"):
        parts.append(str(visual["camera"]))
    keywords = visual.get("keywords") or []
    if isinstance(keywords, list) and keywords:
        parts.extend(str(item) for item in keywords if item)
    palette = visual.get("color_palette") or []
    if isinstance(palette, list) and palette:
        parts.append("color palette: " + ", ".join(str(item) for item in palette if item))
    if outfit.get("description"):
        parts.append("outfit: " + str(outfit["description"]))
    if hair_dict.get("style"):
        parts.append("hair: " + str(hair_dict["style"]))
    descriptors = style.get("additional_descriptors") or []
    if isinstance(descriptors, list):
        parts.extend(str(item) for item in descriptors if item)
    template = str(art.get("template") or "").strip()
    if template:
        parts.append(template.replace("{name}", name).replace("{purpose}", purpose))
    if art.get("positive"):
        parts.append(str(art["positive"]))
    parts.append(slot["shot"])
    if extra:
        parts.append(extra.strip())

    positive = ", ".join(part.strip().rstrip(",") for part in parts if str(part).strip())
    negative = str(art.get("negative") or "").strip()
    return {"positive": positive, "negative": negative, "purpose": purpose}


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
