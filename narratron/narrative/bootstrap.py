"""敘事自舉：把角色一句話膨脹成護照初稿、年齡曲線、因果種子與可拆分鏡的種子劇本。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from narratron.charpass.schema import empty_manifest_dict
from narratron.charpass.vault_bridge import overlay_manifest
from narratron.narrative.world_bible import WorldBible, fit_world

_SCENE_HEADING = re.compile(
    r"^(?:(?:INT|EXT|INT\s*/\s*EXT|INT\./EXT)\.?\s+|場景[：:\s]*)(.+)$",
    re.IGNORECASE,
)
_SECTION = re.compile(
    r"^(角色|人物|道具|場景|Characters?|Props?|Scenes?)[：:\s]*$",
    re.IGNORECASE,
)
_INLINE_SECTION = re.compile(
    r"^(角色|人物|道具|場景|Characters?|Props?|Scenes?)[：:]\s*(.+)$",
    re.IGNORECASE,
)
_AGE = re.compile(
    r"(?<!\d)(\d{1,3})\s*(?:歲|岁|years?\s*old|y/?o)",
    re.IGNORECASE,
)
_NAMED = re.compile(
    r"(?:名叫|名為|名为|名字叫|name(?:d| is))\s*[「『\"']?([^\s，,。：:」』\"']{2,16})",
    re.IGNORECASE,
)
_BRIEF_HINT = re.compile(
    r"歲|岁|years?\s*old|y/?o|風格|风格|style|女孩|男孩|少女|少年|"
    r"公主|王子|騎士|骑士|cute|princess|ghibli|"
    r"一名|一個|一个|一位|小女孩|小男孩",
    re.IGNORECASE,
)
_ACTION_BEAT = re.compile(
    r"走|跑|站在|說|说道|望向|打開|打开|衝|冲|握著|拿著",
)
_STYLE_LOCK = re.compile(r"風格|风格|style|公主風|可愛|可爱|cute|寫實|写实|賽博|赛博")

_FEMALE = re.compile(r"女孩|女童|少女|公主|千金|girl|princess|female|woman|daughter", re.I)
_MALE = re.compile(r"男孩|男童|少年|王子|騎士|骑士|boy|prince|knight|male|son", re.I)
_CUTE = re.compile(r"可愛|可爱|cute|萌|圓潤|圆润|ghibli|吉卜力")
_PRINCESS = re.compile(r"公主|princess|貴族|贵族|千金")
_DARK = re.compile(r"黑暗|冷酷|陰鬱|阴郁|noir|gothic")

_PRINCESS_NAMES = (
    ("艾莉絲", "風鈴草"),
    ("莉雅", "晨露"),
    ("蓓兒", "銀鈴"),
    ("露娜", "星紗"),
    ("芙蘿", "雛菊"),
)
_KNIGHT_NAMES = (
    ("格雷", "石盾"),
    ("卡爾", "北風"),
    ("羅恩", "橡木"),
)
_CYBER_NAMES = (
    ("霓", "零號"),
    ("綾", "核心"),
    ("諾娃", "上行"),
)


@dataclass
class BootstrapResult:
    original_brief: str
    world: WorldBible
    name: str
    alias: str
    age: int
    gender_spectrum: float
    mbti: str
    personality: str
    habits: list[str]
    inner_flaw: str
    occupation: str
    home: str
    family_rank: str
    style_school: str
    lighting: str
    outfit_now: str
    outfit_future: str
    relationships: list[dict[str, str]]
    age_curve: dict[str, Any]
    physiology: dict[str, Any]
    biography: str
    seed_script: str
    manifest: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    def to_preview(self) -> dict[str, Any]:
        return {
            "active": True,
            "original_brief": self.original_brief,
            "world": self.world.to_dict(),
            "character": {
                "name": self.name,
                "alias": self.alias,
                "age": self.age,
                "gender_spectrum": self.gender_spectrum,
                "mbti": self.mbti,
                "personality": self.personality,
                "habits": list(self.habits),
                "inner_flaw": self.inner_flaw,
                "occupation": self.occupation,
                "home": self.home,
                "family_rank": self.family_rank,
                "style_school": self.style_school,
                "lighting": self.lighting,
                "outfit_now": self.outfit_now,
                "outfit_future": self.outfit_future,
            },
            "relationships": list(self.relationships),
            "age_curve": dict(self.age_curve),
            "physiology": dict(self.physiology),
            "biography": self.biography,
            "seed_script": self.seed_script,
            "warnings": list(self.warnings),
            "editable": ["name", "habits", "personality", "inner_flaw", "mbti"],
        }


def looks_like_screenplay(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines:
        return False
    for line in lines:
        upper = line.upper()
        if upper in {"FADE IN:", "FADE IN", "FADE OUT.", "FADE OUT"}:
            return True
        if _SCENE_HEADING.match(line) and not line.startswith(("-", "*")):
            return True
        if _SECTION.match(line) or _INLINE_SECTION.match(line):
            return True
    return False


def looks_like_character_brief(text: str) -> bool:
    compact = str(text or "").strip()
    if not compact or looks_like_screenplay(compact):
        return False
    lines = [line for line in compact.splitlines() if line.strip()]
    if len(lines) > 8 or len(compact) > 800:
        return False
    if not _BRIEF_HINT.search(compact):
        return False
    if _ACTION_BEAT.search(compact) and not _STYLE_LOCK.search(compact):
        return False
    return True


def maybe_bootstrap(text: str, *, overrides: dict[str, Any] | None = None) -> BootstrapResult | None:
    if not looks_like_character_brief(text):
        return None
    return bootstrap_from_brief(text, overrides=overrides)


def identity_from_input(
    name: str,
    *,
    brief: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> BootstrapResult | None:
    """名稱或 brief 若是一句話角色簡述，則膨脹成護照身份。"""
    cleaned = str(name or "").strip()
    source = str(brief or "").strip()
    extra = dict(overrides or {})
    if source and looks_like_character_brief(source):
        if cleaned and not looks_like_character_brief(cleaned):
            extra.setdefault("name", cleaned)
        return bootstrap_from_brief(source, overrides=extra or None)
    if looks_like_character_brief(cleaned):
        return bootstrap_from_brief(cleaned, overrides=extra or None)
    return None


def resolve_ensure_identity(
    name: str,
    *,
    brief: str | None = None,
    base_age: int = 25,
    gender_spectrum: float | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """給 CharacterOS ensure 用：一句話會先膨脹，再回傳確定的姓名／年齡／護照。"""
    cleaned = str(name or "").strip()
    boot = identity_from_input(cleaned, brief=brief)
    if boot is None:
        return {
            "name": cleaned,
            "base_age": int(base_age),
            "gender_spectrum": gender_spectrum,
            "tags": list(tags or []),
            "notes": notes,
            "manifest": manifest if isinstance(manifest, dict) else None,
        }
    age = boot.age if _AGE.search(boot.original_brief) else int(base_age)
    merged_tags = list(tags or [])
    if not merged_tags:
        meta_tags = boot.manifest.get("_meta", {}).get("tags") if isinstance(boot.manifest.get("_meta"), dict) else []
        merged_tags = [str(item) for item in (meta_tags or [])]
    incoming = manifest if isinstance(manifest, dict) else None
    passport = overlay_manifest(boot.manifest, incoming) if incoming else boot.manifest
    return {
        "name": boot.name,
        "base_age": age,
        "gender_spectrum": gender_spectrum if gender_spectrum is not None else boot.gender_spectrum,
        "tags": merged_tags,
        "notes": notes or boot.original_brief,
        "manifest": passport,
    }


def apply_overrides(draft: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(draft)
    if not isinstance(overrides, dict):
        return data
    name = str(overrides.get("name") or "").strip()
    if name:
        data["name"] = name[:16]
    alias = str(overrides.get("alias") or "").strip()
    if alias:
        data["alias"] = alias
    if overrides.get("mbti"):
        data["mbti"] = str(overrides["mbti"]).strip().upper()[:4]
    if overrides.get("personality"):
        data["personality"] = str(overrides["personality"]).strip()
    if overrides.get("inner_flaw"):
        data["inner_flaw"] = str(overrides["inner_flaw"]).strip()
    habits = overrides.get("habits")
    if isinstance(habits, str):
        habits = [item.strip() for item in re.split(r"[\n；;]+", habits) if item.strip()]
    if isinstance(habits, list) and habits:
        data["habits"] = [str(item).strip() for item in habits if str(item).strip()][:8]
    return data


def bootstrap_from_brief(
    text: str,
    *,
    overrides: dict[str, Any] | None = None,
    world: WorldBible | None = None,
    project_id: str | None = None,
) -> BootstrapResult:
    brief = str(text or "").strip()
    chosen_world = world or fit_world(brief, project_id=project_id)
    draft = _inflate_archetype(brief, chosen_world)
    draft = apply_overrides(draft, overrides)
    physiology, warnings = _physiology_gate(int(draft["age"]), float(draft["gender_spectrum"]))
    draft["physiology"] = physiology
    draft["warnings"] = warnings
    draft["biography"] = _biography(draft, chosen_world)
    draft["seed_script"] = _seed_script(draft, chosen_world)
    draft["manifest"] = _build_manifest(draft, chosen_world, brief)
    return BootstrapResult(
        original_brief=brief,
        world=chosen_world,
        name=str(draft["name"]),
        alias=str(draft["alias"]),
        age=int(draft["age"]),
        gender_spectrum=float(draft["gender_spectrum"]),
        mbti=str(draft["mbti"]),
        personality=str(draft["personality"]),
        habits=list(draft["habits"]),
        inner_flaw=str(draft["inner_flaw"]),
        occupation=str(draft["occupation"]),
        home=str(draft["home"]),
        family_rank=str(draft["family_rank"]),
        style_school=str(draft["style_school"]),
        lighting=str(draft["lighting"]),
        outfit_now=str(draft["outfit_now"]),
        outfit_future=str(draft["outfit_future"]),
        relationships=list(draft["relationships"]),
        age_curve=dict(draft["age_curve"]),
        physiology=physiology,
        biography=str(draft["biography"]),
        seed_script=str(draft["seed_script"]),
        manifest=dict(draft["manifest"]),
        warnings=list(warnings),
    )


def _token(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _inflate_archetype(brief: str, world: WorldBible) -> dict[str, Any]:
    age = _parse_age(brief)
    gender = _parse_gender(brief)
    cute = bool(_CUTE.search(brief))
    princess = bool(_PRINCESS.search(brief)) or world.id == "storybook_kingdom"
    dark = bool(_DARK.search(brief))
    name, alias = _pick_name(brief, world, gender, princess)
    mbti = _mbti(cute=cute, princess=princess, dark=dark, gender=gender)
    occupation = _occupation(world, princess, gender)
    habits = _habits(world, princess, cute, age)
    inner_flaw = _inner_flaw(world, princess, cute, age)
    personality = _personality(mbti, cute, princess, occupation)
    style_school = _style_school(brief, world, cute)
    outfit_now, outfit_future = _outfits(world, princess, age, gender)
    relationships = _relationships(world, name)
    return {
        "name": name,
        "alias": alias,
        "age": age,
        "gender_spectrum": gender,
        "mbti": mbti,
        "personality": personality,
        "habits": habits,
        "inner_flaw": inner_flaw,
        "occupation": occupation,
        "home": world.default_scene,
        "family_rank": world.princess_role if princess else "旅人",
        "style_school": style_school,
        "lighting": world.lighting,
        "outfit_now": outfit_now,
        "outfit_future": outfit_future,
        "relationships": relationships,
        "age_curve": _age_curve(age),
        "tags": _tags(brief, world, cute, princess, age),
    }


def _parse_age(brief: str) -> int:
    match = _AGE.search(brief)
    if not match:
        return 12 if _PRINCESS.search(brief) else 18
    try:
        value = int(match.group(1))
    except (TypeError, ValueError):
        return 12
    return max(1, min(120, value))


def _parse_gender(brief: str) -> float:
    female = bool(_FEMALE.search(brief))
    male = bool(_MALE.search(brief))
    if female and not male:
        return 0.0
    if male and not female:
        return 1.0
    return 0.0 if _PRINCESS.search(brief) else 0.5


def _pick_name(brief: str, world: WorldBible, gender: float, princess: bool) -> tuple[str, str]:
    named = _NAMED.search(brief)
    if named:
        given = named.group(1).strip()
        return given[:8], given
    pool: tuple[tuple[str, str], ...]
    if world.id == "cyberpunk_city":
        pool = _CYBER_NAMES
    elif princess and gender <= 0.4:
        pool = _PRINCESS_NAMES
    elif gender >= 0.6:
        pool = _KNIGHT_NAMES
    else:
        pool = _PRINCESS_NAMES
    given, family = pool[_token(brief) % len(pool)]
    alias = f"{given}·{family}"
    return given, alias


def _mbti(*, cute: bool, princess: bool, dark: bool, gender: float) -> str:
    if dark:
        return "INFJ"
    if cute and princess:
        return "ENFJ"
    if cute:
        return "ENFP"
    if gender >= 0.6:
        return "ISTJ"
    return "ISFJ"


def _occupation(world: WorldBible, princess: bool, gender: float) -> str:
    if princess:
        return world.princess_role
    if world.id == "cyberpunk_city":
        return "企業千金" if gender <= 0.4 else "企業繼承者"
    if gender >= 0.6:
        return "見習騎士"
    return "旅人"


def _habits(world: WorldBible, princess: bool, cute: bool, age: int) -> list[str]:
    if world.id == "cyberpunk_city":
        return [
            "睡前必須把窗簾對齊全息廣告的掃描線",
            "緊張時會把袖口的資料晶片轉來轉去",
            "把甜食偷偷塞給護衛的機器犬",
        ]
    if princess and cute and age <= 12:
        return [
            "睡前必須數一遍窗外的螢火蟲",
            "吃胡蘿蔔會偷偷塞給護衛犬",
            "緊張時會不自覺地揪裙擺的蕾絲邊",
        ]
    if princess:
        return [
            "出席前會先對鏡子練習微笑的角度",
            "把真正想說的話寫在袖襯裡",
            "聽見號角會下意識整理領口",
        ]
    return [
        "走路時習慣數自己的腳步",
        "把重要的話重複兩次才放心",
        "緊張時會摸口袋裡的護身符",
    ]


def _inner_flaw(world: WorldBible, princess: bool, cute: bool, age: int) -> str:
    if world.id == "cyberpunk_city":
        return "不信任任何沒有寫進契約的關係"
    if princess and cute and age <= 12:
        return "極度害怕獨自過夜"
    if princess:
        return "把他人的認可當成自己存在的唯一證據"
    return "無法原諒自己曾經掉頭離開的那一次"


def _personality(mbti: str, cute: bool, princess: bool, occupation: str) -> str:
    parts = [f"{mbti} 原型"]
    if cute:
        parts.append("天生樂觀、喜歡把溫暖分給身邊的人")
    if princess:
        parts.append(f"作為{occupation}，極度渴望得到父王或監護者的認可")
    else:
        parts.append("外表安靜，內心把承諾看得比性命還重")
    return "；".join(parts) + "。"


def _style_school(brief: str, world: WorldBible, cute: bool) -> str:
    if "寫實" in brief or "写实" in brief or "photoreal" in brief.lower():
        return "寫實電影靜幀"
    if cute or "可愛" in brief or "ghibli" in brief.lower() or "吉卜力" in brief:
        return "吉卜力與阿德曼混合：高飽和、大眼、圓潤臉頰"
    return world.visual


def _outfits(world: WorldBible, princess: bool, age: int, gender: float) -> tuple[str, str]:
    if world.id == "cyberpunk_city":
        now = "鑲嵌燈帶的短版制服外套與及膝裙，髮側夾著企業徽記"
        future = "全息金線曳地禮服，肩甲改自董事義體"
        return now, future
    if princess and age <= 12:
        return (
            "輕盈的及膝蓬蓬裙與蝴蝶結髮飾，年齡適宜、遮蓋良好",
            "鑲金線的曳地長裙（成年禮，僅文字預留）",
        )
    if princess:
        return ("宮廷常服：收腰長裙與家族紋章披肩", "加冕禮的鑲金線曳地長裙")
    if gender >= 0.6:
        return ("素色短袍與練習用輕甲", "正式騎士披風與家徽胸甲")
    return ("樸素旅行斗篷與及膝裙", "較合身的成年旅人外套")


def _relationships(world: WorldBible, protagonist: str) -> list[dict[str, str]]:
    if world.id == "cyberpunk_city":
        return [
            {
                "name": "茉德",
                "role": "監護人",
                "note": "表面吐槽，實際替她擋掉董事會的窺探",
            },
            {
                "name": "格雷",
                "role": "近身教官",
                "note": "嚴肅寡言，堅持她必須學會關掉自己的定位器",
            },
        ]
    return [
        {
            "name": "茉德",
            "role": "奶媽",
            "note": f"負責吐槽，其實最護著{protagonist}",
        },
        {
            "name": "格雷",
            "role": "劍術老師",
            "note": "嚴肅寡言，堅持她必須學會保護自己",
        },
    ]


def _tags(brief: str, world: WorldBible, cute: bool, princess: bool, age: int) -> list[str]:
    tags = [world.name, f"{age}歲"]
    if cute:
        tags.append("可愛")
    if princess:
        tags.append("公主風")
    if "風格" in brief or "风格" in brief:
        tags.append("風格自舉")
    return tags


def _age_curve(age: int) -> dict[str, Any]:
    present = max(1, min(120, int(age)))
    keyframes = [present]
    if present < 18:
        keyframes.append(18)
    elif present not in {30, 45, 60} and present < 60:
        nearest = min((30, 45, 60), key=lambda item: abs(item - present))
        if nearest != present:
            keyframes.append(nearest)
    logic_only = [item for item in (35, 60) if item not in keyframes and item != present]
    return {
        "present": present,
        "generate_now": [present],
        "keyframes": sorted(set(keyframes)),
        "logic_only": logic_only,
        "method": "lazy_narrative_heat",
        "enqueue": False,
        "span": False,
    }


def _expected_physiology(age: int, gender_spectrum: float) -> dict[str, float]:
    """以年齡推估合理體貌；兒童不得接近成人尺度。"""
    years = max(1, min(80, int(age)))
    female = gender_spectrum <= 0.4
    if years <= 3:
        height, weight, head = 95.0, 14.0, 0.22
    elif years <= 8:
        height, weight, head = (127.0, 25.0, 0.18) if female else (128.0, 26.0, 0.18)
    elif years <= 12:
        height, weight, head = (147.0, 38.0, 0.16) if female else (149.0, 40.0, 0.16)
    elif years <= 17:
        height, weight, head = (160.0, 50.0, 0.14) if female else (170.0, 58.0, 0.13)
    else:
        height, weight, head = (162.0, 54.0, 0.13) if female else (175.0, 70.0, 0.13)
    return {
        "height_cm": height,
        "weight_kg": weight,
        "head_ratio": head,
    }


def _physiology_gate(age: int, gender_spectrum: float) -> tuple[dict[str, Any], list[str]]:
    expected = _expected_physiology(age, gender_spectrum)
    height = expected["height_cm"]
    weight = expected["weight_kg"]
    warnings: list[str] = []
    adult_floor_kg = 48.0
    if age < 13 and weight >= adult_floor_kg:
        warnings.append("體重不可接近成人尺度，已回退至兒童生理曲線")
        weight = expected["weight_kg"]
    if age < 13 and height >= 160:
        warnings.append("身高不可套用成人比例，已回退至兒童生理曲線")
        height = expected["height_cm"]
    return (
        {
            "height_cm": height,
            "weight_kg": weight,
            "head_ratio": expected["head_ratio"],
            "source": "physiology_curve",
            "adult_weight_floor_kg": adult_floor_kg,
        },
        warnings,
    )


def _biography(draft: dict[str, Any], world: WorldBible) -> str:
    habits = "；".join(draft["habits"])
    relations = "、".join(f"{item['name']}（{item['role']}）" for item in draft["relationships"])
    curve = draft["age_curve"]
    keyframes = "、".join(f"{item}歲" for item in curve.get("keyframes") or [])
    logic = "、".join(f"{item}歲" for item in curve.get("logic_only") or []) or "暫不預生成"
    return (
        f"{draft['name']}（{draft['alias']}）現年 {draft['age']} 歲，是{world.name}裡的{draft['occupation']}。"
        f"她住在{draft['home']}，身份是{draft['family_rank']}。"
        f"性格屬 {draft['mbti']}：{draft['personality']}"
        f"日常習慣包括：{habits}。"
        f"這些癖好會被寫進因果鏈，成為未來劇情衝突的引信。"
        f"身邊常出現 {relations}；他們不預先生成圖像，只存在關係圖譜裡，供分鏡調度時點名。"
        f"視覺上鎖定「{draft['style_school']}」，標準光型為「{draft['lighting']}」。"
        f"此刻服裝是{draft['outfit_now']}；若敘事走到成年禮，服裝演化為{draft['outfit_future']}。"
        f"年齡軸採延遲生成：現在進行式 {draft['age']} 歲需高精度；關鍵幀 {keyframes}；"
        f"{logic} 僅存文字概念，直到劇本因果鏈真正觸及。"
        f"內在矛盾是「{draft['inner_flaw']}」。當夜裡城堡失守或守護者離開，這個種子會自動觸發錯誤判斷，"
        f"把純真推向悲劇或逆襲，完成敘事閉環。"
        f"世界觀錨點：{world.social_logic}"
    )


def _seed_script(draft: dict[str, Any], world: WorldBible) -> str:
    name = draft["name"]
    age = draft["age"]
    scene = draft["home"]
    nanny = draft["relationships"][0]
    tutor = draft["relationships"][1]
    habit = draft["habits"][0]
    flaw = draft["inner_flaw"]
    heading = f"INT. {scene} 寢宮 - NIGHT" if world.era != "cyberpunk" else f"INT. {scene} - NIGHT"
    return f"""角色：
- {name}：{age}歲，{draft['occupation']}，{draft['outfit_now']}
- {nanny['name']}：{nanny['note']}
- {tutor['name']}：{tutor['note']}

場景：
- {scene}：{world.visual}，{world.lighting}

{heading}

{age} 歲的{name}揪著裙擺，望向窗外。她正在{habit.rstrip('。')}。

{name}
今晚……可以留下一盞燈嗎？

{nanny['name']}
又來了？這裡沒有怪物。

{tutor['name']}站在門邊，沒有說話。走廊的燭火忽然滅了一盞。
{name}把臉埋進枕頭，因為她{flaw}。
""".strip()


def _build_manifest(draft: dict[str, Any], world: WorldBible, brief: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    entity_id = f"character-{draft['name']}"
    base = empty_manifest_dict()
    physiology = draft["physiology"]
    curve = draft["age_curve"]
    overlay = {
        "_meta": {
            "character_name": draft["name"],
            "character_alias": [draft["alias"]],
            "entity_id": entity_id,
            "created_at": now,
            "updated_at": now,
            "created_by": "narrative_bootstrap",
            "tags": draft.get("tags") or [],
            "description": draft["biography"],
            "notes": brief,
        },
        "_identity": {
            "name": draft["name"],
            "aliases": [draft["alias"]],
            "entity_id": entity_id,
            "gender_spectrum": draft["gender_spectrum"],
            "age_appearance": str(draft["age"]),
            "note": f"{draft['occupation']}；{draft['family_rank']}",
            "ip_adapter": {"enabled": True, "weight": 0.9, "model": "ip-adapter-faceid-plusv2"},
            "lock_rules": {
                "face_consistency_threshold": 0.9,
                "allow_expression_change": True,
                "allow_aging_progression": True,
                "forbidden_regions": ["hands_extra_digits"],
            },
        },
        "_body": {
            "height_cm": physiology["height_cm"],
            "skeleton": {
                "head_ratio": physiology["head_ratio"],
                "height_cm": physiology["height_cm"],
                "weight_kg": physiology["weight_kg"],
            },
            "build": "child" if draft["age"] < 13 else "adult",
        },
        "_style": {
            "outfit": {
                "description": draft["outfit_now"],
                "evolution": {
                    str(draft["age"]): draft["outfit_now"],
                    "18": draft["outfit_future"],
                },
            },
            "hair": {"style": "蝴蝶結髮飾" if draft["age"] <= 12 else "束起", "texture": "soft"},
            "character_style": {
                "visual": {
                    "medium": "hand-drawn animation still",
                    "aesthetic": draft["style_school"],
                    "lighting": draft["lighting"],
                    "keywords": ["storybook", "identity-lock", "age-appropriate"],
                    "note": world.visual,
                },
                "art_prompt": {
                    "positive": (
                        f"{draft['style_school']}, {draft['lighting']}, "
                        f"exactly {draft['age']} years old, {draft['outfit_now']}"
                    ),
                    "negative": (
                        "extra fingers, six fingers, mutated hands, adult body on child, "
                        "nsfw, sexualized, photoreal adult proportions, watermark"
                    ),
                    "strength": 1.0,
                },
                "narrative": {
                    "tone": "溫暖而怯場",
                    "speech_pattern": "短句、會把疑問句說成請求",
                    "sample_lines": ["今晚……可以留下一盞燈嗎？"],
                },
            },
        },
        "_expression": {"base_emotion": "hopeful", "default": "hopeful"},
        "_causal": {
            "evolution_log": [
                {
                    "event": "causal_seed",
                    "cause": "敘事自舉植入內在矛盾",
                    "effect": draft["inner_flaw"],
                    "description": "供 Parser／Director 在夜襲、獨處鏡頭自動觸發恐懼判斷",
                    "at": now,
                }
            ],
            "current_state_snapshot": {
                "inner_flaw": draft["inner_flaw"],
                "habits": draft["habits"],
                "mbti": draft["mbti"],
                "world_id": world.id,
                "age_curve": curve,
                "relationships": draft["relationships"],
            },
        },
        "_constraints": {
            "must_always": [
                f"exactly {draft['age']} years old",
                "age-appropriate clothing",
                "same named person as identity lock",
            ],
            "must_never": [
                "extra fingers",
                "six fingers",
                "adult body proportions on a child",
                "sexualized child",
                "weight of an adult on a child body",
            ],
            "forbidden": ["six_fingers", "adult_child_body", "nsfw_minor"],
            "required": ["identity_anchor", "age_lock"],
            "quality_floor": {"face_consistency_min": 0.9, "body_proportion_tolerance": 0.05},
        },
        "_physics": {"mass_kg": physiology["weight_kg"]},
    }
    return overlay_manifest(base, overlay)
