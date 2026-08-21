"""依歲數彙整角色面部／T 型資產，供年齡點選預覽 UI。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from characteros.services.age_span import AGE_SPAN_END, AGE_SPAN_START

_AGE_TOKEN_RE = re.compile(r"(?:^|[_/\-])age[_-]?(\d{1,3})(?:[_/\-]|$)", re.IGNORECASE)


def _age_token(age: int) -> str:
    return f"{int(age):03d}"


def _rel_if_file(folder: Path, path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.relative_to(folder).as_posix()
    except ValueError:
        return None


def _prefer_newest(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    return max(paths, key=lambda item: item.stat().st_mtime)


def _paths_matching_age(root: Path, age: int) -> list[Path]:
    if not root.is_dir():
        return []
    token = _age_token(age)
    matched: list[Path] = []
    for path in root.rglob("*.png"):
        text = path.as_posix()
        name = path.name
        if f"age_{token}" in name or f"age-{token}" in name or f"/age_{token}/" in text:
            matched.append(path)
            continue
        found = _AGE_TOKEN_RE.search(name) or _AGE_TOKEN_RE.search(text)
        if found and int(found.group(1)) == int(age):
            matched.append(path)
    return matched


def resolve_age_asset(folder: Path, *, purpose: str, age: int) -> str | None:
    """找指定歲數的 face_detail / tpose PNG（相對角色目錄）。"""
    token = _age_token(age)
    purpose = str(purpose or "").strip()
    preferred = [
        folder / "assets" / purpose / f"ref_{purpose}_age_{token}_001.png",
        folder / "assets" / purpose / f"age_{token}" / f"ref_{purpose}_age_{token}_001.png",
        folder / "assets" / purpose / f"age_{token}" / f"{purpose}_{token}.png",
    ]
    for path in preferred:
        rel = _rel_if_file(folder, path)
        if rel:
            return rel
    hit = _prefer_newest(_paths_matching_age(folder / "assets" / purpose, age))
    return _rel_if_file(folder, hit) if hit else None


def _asset_url(character_id: int, path: str | None) -> str | None:
    cleaned = str(path or "").strip().lstrip("/")
    if not cleaned:
        return None
    return f"/api/v1/characters/{int(character_id)}/assets/{cleaned}"


def build_age_gallery(
    folder: Path,
    *,
    character_id: int,
    character_name: str | None = None,
    age_start: int = AGE_SPAN_START,
    age_end: int = AGE_SPAN_END,
) -> dict[str, Any]:
    start = max(1, min(int(age_start), 80))
    end = max(start, min(int(age_end), 80))
    items: list[dict[str, Any]] = []
    face_count = 0
    tpose_count = 0
    for age in range(start, end + 1):
        face = resolve_age_asset(folder, purpose="face_detail", age=age)
        tpose = resolve_age_asset(folder, purpose="tpose", age=age)
        if face:
            face_count += 1
        if tpose:
            tpose_count += 1
        items.append(
            {
                "age": age,
                "face_detail_asset_path": face,
                "tpose_asset_path": tpose,
                "face_detail_url": _asset_url(character_id, face),
                "tpose_url": _asset_url(character_id, tpose),
                "has_face_detail": bool(face),
                "has_tpose": bool(tpose),
            }
        )
    return {
        "character_id": int(character_id),
        "character_name": character_name,
        "age_start": start,
        "age_end": end,
        "face_count": face_count,
        "tpose_count": tpose_count,
        "items": items,
    }
