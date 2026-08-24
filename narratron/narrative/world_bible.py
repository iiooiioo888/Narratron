"""世界觀擬合：讀專案 World Bible；沒有則錨在預設童話王國。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _repo_data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


@dataclass(frozen=True)
class WorldBible:
    id: str
    name: str
    era: str
    social_logic: str
    visual: str
    default_scene: str
    lighting: str
    princess_role: str
    keywords: tuple[str, ...] = ()
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "era": self.era,
            "social_logic": self.social_logic,
            "visual": self.visual,
            "default_scene": self.default_scene,
            "lighting": self.lighting,
            "princess_role": self.princess_role,
            "keywords": list(self.keywords),
            **self.extras,
        }


STORYBOOK_KINGDOM = WorldBible(
    id="storybook_kingdom",
    name="童話王國",
    era="storybook",
    social_logic="貴族血脈與宮廷禮儀；小魔法已融入日常，夜巡仍由護衛負責。",
    visual="手繪童話、高飽和、圓潤造型、柔光",
    default_scene="晨露城堡",
    lighting="晨間側逆光 Golden Hour",
    princess_role="國王最小的女兒",
    keywords=("童話", "公主", "城堡", "王國", "storybook", "fairy"),
)

MEDIEVAL_FANTASY = WorldBible(
    id="medieval_fantasy",
    name="中世紀奇幻",
    era="medieval",
    social_logic="封建分封與騎士誓約；魔法受教會與宮廷雙重監管。",
    visual="油畫質感、燭光石堡、紋章與鎖子甲",
    default_scene="石堡大廳",
    lighting="燭火與高窗側光",
    princess_role="貴族血脈的繼承人",
    keywords=("中世紀", "奇幻", "騎士", "魔法", "龍", "medieval", "fantasy"),
)

CYBERPUNK_CITY = WorldBible(
    id="cyberpunk_city",
    name="霓虹企業城",
    era="cyberpunk",
    social_logic="巨型企業取代王國；血統改寫成股權與基因專利。",
    visual="霓虹濕地、全息廣告、義體高光",
    default_scene="雲端總部頂層",
    lighting="霓虹側光與雨夜反射",
    princess_role="巨型企業的千金",
    keywords=("賽博", "賽博朋克", "企業", "霓虹", "義體", "cyberpunk", "neon"),
)

CATALOG: tuple[WorldBible, ...] = (STORYBOOK_KINGDOM, MEDIEVAL_FANTASY, CYBERPUNK_CITY)


def load_world_bible(project_id: str | None = None, *, data_dir: Path | None = None) -> WorldBible | None:
    """專案若有 `data/world_bible.json` 則採用；否則回傳 None 讓擬合走預設。"""
    root = data_dir or _repo_data_dir()
    path = root / "world_bible.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    worlds = raw.get("worlds") if isinstance(raw.get("worlds"), list) else [raw]
    picked = None
    want = str(project_id or raw.get("active_id") or "").strip()
    for item in worlds:
        if not isinstance(item, dict):
            continue
        if want and str(item.get("id") or "") == want:
            picked = item
            break
        if picked is None:
            picked = item
    if not isinstance(picked, dict):
        return None
    return WorldBible(
        id=str(picked.get("id") or "custom"),
        name=str(picked.get("name") or "自訂世界"),
        era=str(picked.get("era") or "custom"),
        social_logic=str(picked.get("social_logic") or ""),
        visual=str(picked.get("visual") or ""),
        default_scene=str(picked.get("default_scene") or "未標場景"),
        lighting=str(picked.get("lighting") or ""),
        princess_role=str(picked.get("princess_role") or "貴族之後"),
        keywords=tuple(str(item) for item in (picked.get("keywords") or []) if str(item).strip()),
        extras={
            key: value
            for key, value in picked.items()
            if key
            not in {
                "id",
                "name",
                "era",
                "social_logic",
                "visual",
                "default_scene",
                "lighting",
                "princess_role",
                "keywords",
            }
        },
    )


def fit_world(text: str, *, project_id: str | None = None, data_dir: Path | None = None) -> WorldBible:
    stored = load_world_bible(project_id, data_dir=data_dir)
    if stored is not None:
        return stored
    blob = str(text or "")
    lowered = blob.lower()
    scored: list[tuple[int, WorldBible]] = []
    for world in CATALOG:
        hits = sum(1 for key in world.keywords if key.lower() in lowered or key in blob)
        if hits:
            scored.append((hits, world))
    if scored:
        scored.sort(key=lambda item: (-item[0], item[1].id))
        return scored[0][1]
    return STORYBOOK_KINGDOM
