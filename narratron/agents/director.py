"""Director（調度器）：將故事拆解為分鏡，決定鏡頭語言與時序節奏。"""

from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from narratron.agents.parser import Parser, _scene_title
from narratron.agents.state import AgentState
from narratron.vault.chroma import Chroma
from narratron.vault.redis_cache import Redis
from narratron.vault.schema import Entity, EntityKind, Shot, TraceRecord
from narratron.vault.state_vault import StateVault, get_default_vault

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
_LIST_ITEM = re.compile(r"^[-*•]\s+(.+)$")
_MOVE = re.compile(r"走|跑|衝|冲|跟|walk|run|rush|dash", re.IGNORECASE)
_SPEAK = re.compile(r"[：:]|說|道|dialogue", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[。！？.!?]+[\"'」』）)]*$")
_SENTENCE_PART = re.compile(r".+?(?:[。！？.!?]+[\"'」』）)]*|$)")
_LINE_CONTINUE = re.compile(r"[，,、；;]$")
_CHARACTER_PRONOUN = re.compile(
    r"她們|他们|她们|他們|該角色|该角色|這個人|这个人|"
    r"(?:^|[，。！？；：、\s]|然後|然后|接著|接着)[她他其](?:們|们)?|"
    r"\b(?:he|she|they|him|her|them|the character)\b",
    re.IGNORECASE,
)
_AGE = re.compile(r"(?<!\d)(\d{1,3})\s*(?:歲|岁|years?\s*old|y/o)", re.IGNORECASE)
_KEYFRAME = re.compile(r"關鍵(?:幀|帧|鏡頭)|keyframe", re.IGNORECASE)
_WEATHER = (
    ("storm", re.compile(r"暴雨|雷雨|風暴|风暴|storm|thunder", re.IGNORECASE)),
    ("snow", re.compile(r"下雪|雪地|飄雪|飘雪|snow|blizzard", re.IGNORECASE)),
    ("fog", re.compile(r"霧|雾|濃霧|浓雾|fog|mist", re.IGNORECASE)),
    ("rain", re.compile(r"雨|淋濕|淋湿|rain|wet hair", re.IGNORECASE)),
    ("clear", re.compile(r"晴|陽光|阳光|clear sky|sunny", re.IGNORECASE)),
)
_EMOTIONS = (
    ("fearful", re.compile(r"恐懼|恐惧|害怕|驚恐|惊恐|fear|terrified", re.IGNORECASE)),
    ("angry", re.compile(r"憤怒|愤怒|生氣|生气|怒|angry|furious", re.IGNORECASE)),
    ("sad", re.compile(r"悲傷|悲伤|難過|难过|哭|落淚|落泪|sad|cry", re.IGNORECASE)),
    ("happy", re.compile(r"開心|开心|高興|高兴|微笑|笑著|笑着|happy|smil", re.IGNORECASE)),
    ("determined", re.compile(r"堅定|坚定|決心|决心|determined|resolute", re.IGNORECASE)),
)
_INJURY_LEVELS = (
    (0.9, re.compile(r"重傷|重伤|深(?:層|层)?傷口|大量出血|severe wound", re.IGNORECASE)),
    (0.7, re.compile(r"流血|滲血|渗血|血跡|血迹|blood|wound", re.IGNORECASE)),
    (0.4, re.compile(r"受傷|受伤|傷口|伤口|瘀傷|瘀伤|繃帶|绷带|injur|bruise|bandage", re.IGNORECASE)),
    (0.2, re.compile(r"傷疤|伤疤|傷痕|伤痕|疤|scar", re.IGNORECASE)),
)
_AGE_ANCHORS = (5, 18, 30, 45, 60, 80)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _duration_ms(text: str) -> int:
    return max(1500, min(8000, 1200 + len(text.strip()) * 40))


def _camera(beat: str, index: int, speaking: bool, character_count: int) -> str:
    if index == 0:
        return "全景 Establishing"
    if speaking or _SPEAK.search(beat):
        return "特寫 Close-up"
    # If there's clear action/motion cues, prefer a tracking camera.
    # This improves shot language completeness when multiple characters exist.
    if _MOVE.search(beat):
        return "跟拍 Tracking"
    if character_count >= 2:
        return "過肩 Over-the-shoulder"
    return "中景 Medium"


def _is_speaking_beat(beat: str, characters: list[Entity]) -> bool:
    text = beat.lstrip()
    for character in characters:
        name = character.name.strip()
        if not name or not text.startswith(name):
            continue
        remainder = text[len(name) :]
        if remainder.startswith(("：", ":")) or remainder[:1].isspace():
            return True
    return False


def _first_match(text: str, rules: tuple[tuple[str, re.Pattern[str]], ...]) -> str | None:
    for value, pattern in rules:
        if pattern.search(text):
            return value
    return None


def _injury_level(text: str) -> float | None:
    for level, pattern in _INJURY_LEVELS:
        if pattern.search(text):
            return level
    return None


def _age_plan(age: int | None) -> dict[str, Any] | None:
    if age is None:
        return None
    target = max(1, min(120, int(age)))
    if target in _AGE_ANCHORS:
        return {"target": target, "anchors": [target], "blend": 0.0, "method": "exact_anchor"}
    lower = max((item for item in _AGE_ANCHORS if item < target), default=_AGE_ANCHORS[0])
    upper = min((item for item in _AGE_ANCHORS if item > target), default=_AGE_ANCHORS[-1])
    if lower == upper:
        return {"target": target, "anchors": [lower], "blend": 0.0, "method": "nearest_anchor"}
    blend = round((target - lower) / (upper - lower), 4)
    return {
        "target": target,
        "anchors": [lower, upper],
        "blend": blend,
        "method": "latent_interpolation",
    }


def _visual_cache_key(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _age_from_entity(character: Entity) -> int | None:
    """護照上的現在年齡；分鏡沒寫歲數時用來填 variant，但不因此變成關鍵幀。"""
    manifest = character.payload.get("charpass")
    if not isinstance(manifest, dict):
        return None
    identity = manifest.get("_identity") if isinstance(manifest.get("_identity"), dict) else {}
    raw = identity.get("age_appearance")
    if raw is None:
        return None
    text = str(raw).strip()
    try:
        return max(1, min(120, int(text)))
    except (TypeError, ValueError):
        match = re.search(r"(?<!\d)(\d{1,3})(?!\d)", text)
        return max(1, min(120, int(match.group(1)))) if match else None


def _character_profile_revision(character: Entity) -> dict[str, Any]:
    manifest = character.payload.get("charpass")
    if not isinstance(manifest, dict):
        return {
            "character_id": character.id,
            "profile_version": 1,
            "manifest_fingerprint": None,
        }
    meta = manifest.get("_meta") if isinstance(manifest.get("_meta"), dict) else {}
    try:
        profile_version = max(1, int(meta.get("profile_version") or 1))
    except (TypeError, ValueError):
        profile_version = 1
    visual_layers = {
        key: manifest.get(key)
        for key in ("_identity", "_body", "_style", "_constraints")
        if isinstance(manifest.get(key), dict)
    }
    return {
        "character_id": character.id,
        "profile_version": profile_version,
        "manifest_fingerprint": _visual_cache_key(visual_layers),
    }


def _characters_in_beat(beat: str, characters: list[Entity]) -> list[Entity]:
    return [
        item
        for item in sorted(characters, key=lambda value: len(value.name), reverse=True)
        if item.name and item.name in beat
    ]


class Director:
    def __init__(
        self,
        vault: StateVault | None = None,
        *,
        persist: bool = True,
        chroma: Chroma | None = None,
        redis: Redis | None = None,
        parser: Parser | None = None,
    ) -> None:
        self._persist = persist
        self._vault = vault
        self._chroma = chroma if chroma is not None else Chroma()
        self._redis = redis if redis is not None else Redis()
        self._parser = parser

    def _vault_or_default(self) -> StateVault | None:
        if not self._persist:
            return self._vault
        return self._vault if self._vault is not None else get_default_vault()

    def direct(self, state: AgentState) -> AgentState:
        working = state
        if not working.entities:
            parser = self._parser or Parser(
                vault=self._vault,
                persist=self._persist,
                chroma=self._chroma,
            )
            working = parser.parse(working)

        shots, extra_traces = self.breakdown(working)
        vault = self._vault_or_default()
        if vault is not None:
            vault.upsert_shots(shots)
            vault.trace_log().append_many(extra_traces)
            self._cache_shots(shots)

        traces = list(working.traces) + extra_traces
        return working.model_copy(update={"shots": shots, "traces": traces})

    def breakdown(self, state: AgentState) -> tuple[list[Shot], list[TraceRecord]]:
        scenes = [item for item in state.entities if item.kind is EntityKind.SCENE]
        characters = [item for item in state.entities if item.kind is EntityKind.CHARACTER]
        default_scene = scenes[0] if scenes else Entity(
            id="scene-untitled",
            kind=EntityKind.SCENE,
            name="未標場景",
        )
        blocks = self._scene_blocks(state.script, scenes, default_scene)
        character_names = {item.name.strip() for item in characters if item.name.strip()}
        shots: list[Shot] = []
        traces: list[TraceRecord] = []
        order = 0
        for scene, beats in blocks:
            if not beats:
                beats = [scene.name]
            active_characters: list[Entity] = []
            for index, beat in enumerate(self._compact_beats(beats, character_names)):
                order += 1
                matched_characters = _characters_in_beat(beat, characters)
                if matched_characters:
                    active_characters = matched_characters
                elif _CHARACTER_PRONOUN.search(beat):
                    if active_characters:
                        matched_characters = active_characters
                    elif len(characters) == 1:
                        matched_characters = characters
                speaking = _is_speaking_beat(beat, characters)
                camera = _camera(beat, index, speaking, len(matched_characters))
                visual = self._visual_requirements(
                    beat,
                    scene=scene,
                    matched_characters=matched_characters,
                    scene_first=index == 0,
                    camera_language=camera,
                )
                shot_id = f"shot-{order:04d}"
                shot = Shot(
                    id=shot_id,
                    scene_id=scene.id,
                    order=order,
                    camera_language=camera,
                    duration_ms=_duration_ms(beat),
                    payload={
                        "beat": beat,
                        "scene_name": scene.name,
                        "visual_requirements": visual,
                        "generation_snapshot": {
                            "status": "pending",
                            "fallback": "base_body",
                            "asset_uri": None,
                            "transaction_id": f"generation-{shot_id}-{visual['cache_key'][:12]}",
                        },
                    },
                )
                shots.append(shot)
                traces.append(
                    TraceRecord(
                        id=f"trace-shot-{shot.id}",
                        entity_id=scene.id,
                        shot_id=shot.id,
                        happened_at=_now(),
                        cause=f"分鏡 {order}",
                        effect=camera,
                        payload={
                            "beat": beat[:200],
                            "visual_cache_key": visual["cache_key"],
                            "generation_status": "pending",
                        },
                    )
                )
        return shots, traces

    def _visual_requirements(
        self,
        beat: str,
        *,
        scene: Entity,
        matched_characters: list[Entity],
        scene_first: bool,
        camera_language: str,
    ) -> dict[str, Any]:
        scene_note = str(scene.payload.get("note") or "")
        context = f"{scene.name} {scene_note} {beat}"
        ages = [int(value) for value in _AGE.findall(beat)]
        explicit_age = ages[0] if ages else None
        inherited_age = None
        if explicit_age is None:
            for character in matched_characters:
                inherited_age = _age_from_entity(character)
                if inherited_age is not None:
                    break
        target_age = explicit_age if explicit_age is not None else inherited_age
        weather = _first_match(context, _WEATHER)
        emotion = _first_match(beat, _EMOTIONS)
        injury = _injury_level(beat)
        continuity_tokens: list[str] = []
        for character in matched_characters:
            for token in character.payload.get("continuity_tokens") or []:
                if token not in continuity_tokens:
                    continuity_tokens.append(str(token))

        variant_params = {
            "age": target_age,
            "emotion": emotion,
            "scene": scene.name,
            "weather": weather,
            "injury": injury,
        }
        profile_revisions = [
            _character_profile_revision(item)
            for item in matched_characters
        ]
        variant_cache_payload = {
            "character_ids": [item.id for item in matched_characters],
            "profile_revisions": profile_revisions,
            "variant_params": variant_params,
            "continuity_tokens": continuity_tokens,
        }
        variant_cache_key = _visual_cache_key(variant_cache_payload)
        shot_cache_payload = {
            "variant_cache_key": variant_cache_key,
            "beat": re.sub(r"\s+", " ", beat).strip().lower(),
            "camera_language": camera_language,
        }
        is_keyframe = bool(
            scene_first
            or _KEYFRAME.search(beat)
            or explicit_age is not None
            or injury is not None
        )
        return {
            **variant_cache_payload,
            "age_plan": _age_plan(target_age),
            "identity_anchor": {
                "required": bool(matched_characters),
                "source": "charpass",
            },
            "generation_mode": "lazy",
            "enqueue": False,
            "keyframe": is_keyframe,
            "render_tier": "final" if is_keyframe else "draft",
            "variant_cache_key": variant_cache_key,
            "cache_key": _visual_cache_key(shot_cache_payload),
        }

    def _scene_blocks(
        self,
        script: str,
        scenes: list[Entity],
        default_scene: Entity,
    ) -> list[tuple[Entity, list[str]]]:
        lines = script.replace("\r\n", "\n").split("\n")
        buckets: list[tuple[Entity, list[str]]] = [(default_scene, [])]
        in_metadata_list = False
        for raw in lines:
            line = raw.strip()
            if not line:
                if buckets[-1][1] and buckets[-1][1][-1]:
                    buckets[-1][1].append("")
                continue
            if line.upper() in {
                "FADE IN:",
                "FADE IN",
                "FADE OUT.",
                "FADE OUT",
            }:
                continue
            if _SECTION.match(line):
                in_metadata_list = True
                continue
            if _INLINE_SECTION.match(line):
                in_metadata_list = False
                continue
            heading = _SCENE_HEADING.match(line)
            if heading and not line.startswith("-") and not line.startswith("*"):
                in_metadata_list = False
                title = _scene_title(heading.group(1))
                matched = self._match_scene(title, scenes) or default_scene
                if buckets[-1][1] or buckets[-1][0].id != matched.id:
                    buckets.append((matched, []))
                else:
                    buckets[-1] = (matched, [])
                continue
            if in_metadata_list:
                if _LIST_ITEM.match(line):
                    continue
                # 清單後第一個非清單行就是正文；不可等到下一個場景標題，
                # 否則「標題 → metadata → 對白」格式會遺失整段劇情。
                in_metadata_list = False
            if line.startswith("參考圖") or line.startswith("!["):
                continue
            buckets[-1][1].append(line)

        merged: list[tuple[Entity, list[str]]] = []
        for scene, beats in buckets:
            while beats and not beats[-1]:
                beats.pop()
            if beats or (merged and merged[-1][0].id != scene.id):
                merged.append((scene, beats))
        return merged or [(default_scene, [])]

    def _match_scene(self, title: str, scenes: list[Entity]) -> Entity | None:
        compact = re.sub(r"\s+", "", title)
        for scene in scenes:
            if re.sub(r"\s+", "", scene.name) in compact or compact in re.sub(r"\s+", "", scene.name):
                return scene
        return scenes[0] if scenes else None

    def _compact_beats(self, lines: list[str], character_names: set[str]) -> list[str]:
        beats: list[str] = []
        buf: list[str] = []
        active_speaker: str | None = None

        def flush() -> None:
            nonlocal buf
            if buf:
                beats.append(" ".join(buf))
                buf = []

        for line in lines:
            if not line:
                flush()
                active_speaker = None
                continue
            cue = _character_cue(line, character_names)
            if cue is not None:
                flush()
                active_speaker = cue
                continue
            inline = _inline_character_dialogue(line, character_names)
            if inline is not None:
                flush()
                speaker, dialogue = inline
                parts = [item.strip() for item in _SENTENCE_PART.findall(dialogue) if item.strip()]
                for part in parts or [dialogue]:
                    beats.append(f"{speaker}：{part}")
                active_speaker = None
                continue
            parts = [item.strip() for item in _SENTENCE_PART.findall(line) if item.strip()]
            for part in parts or [line]:
                text = f"{active_speaker} {part}" if active_speaker else part
                buf.append(text)
                if _SENTENCE_END.search(part):
                    flush()
            # 中文分鏡常以換行當一句，沒有句號。未以逗號續行就結束本 beat。
            if buf and not _LINE_CONTINUE.search(line.rstrip()):
                flush()
        flush()
        return [beat for beat in beats if beat.strip()]

    def _cache_shots(self, shots: list[Shot]) -> None:
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, str]] = []
        for shot in shots:
            payload = json.dumps(shot.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
            self._redis.set(f"shot:{shot.id}", payload, ttl_seconds=3600)
            ids.append(shot.id)
            documents.append(f"{shot.camera_language} {shot.payload.get('beat', '')}")
            metadatas.append({"scene_id": shot.scene_id, "order": str(shot.order)})
        if ids:
            self._chroma.upsert(ids, documents, metadatas)


def _character_cue(line: str, character_names: set[str]) -> str | None:
    stripped = line.strip()
    return stripped if stripped in character_names else None


def _inline_character_dialogue(
    line: str,
    character_names: set[str],
) -> tuple[str, str] | None:
    for name in sorted(character_names, key=len, reverse=True):
        match = re.fullmatch(rf"{re.escape(name)}\s*[：:]\s*(.+)", line)
        if match:
            return name, match.group(1).strip()
    return None


def director_node(state: AgentState) -> AgentState:
    return Director().direct(state)
