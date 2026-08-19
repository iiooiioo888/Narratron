"""Director（調度器）：將故事拆解為分鏡，決定鏡頭語言與時序節奏。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

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
_MOVE = re.compile(r"走|跑|衝|冲|跟|walk|run|rush|dash", re.IGNORECASE)
_SPEAK = re.compile(r"[：:]|說|道|dialogue", re.IGNORECASE)


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
        shots: list[Shot] = []
        traces: list[TraceRecord] = []
        order = 0
        for scene, beats in blocks:
            if not beats:
                beats = [scene.name]
            for index, beat in enumerate(beats):
                order += 1
                speaking = any(char.name and char.name in beat for char in characters)
                camera = _camera(beat, index, speaking, len(characters))
                shot = Shot(
                    id=f"shot-{order:04d}",
                    scene_id=scene.id,
                    order=order,
                    camera_language=camera,
                    duration_ms=_duration_ms(beat),
                    payload={"beat": beat, "scene_name": scene.name},
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
                        payload={"beat": beat[:200]},
                    )
                )
        return shots, traces

    def _scene_blocks(
        self,
        script: str,
        scenes: list[Entity],
        default_scene: Entity,
    ) -> list[tuple[Entity, list[str]]]:
        lines = script.replace("\r\n", "\n").split("\n")
        buckets: list[tuple[Entity, list[str]]] = [(default_scene, [])]
        in_cast_list = False
        for raw in lines:
            line = raw.strip()
            if not line or line.upper() in {"FADE IN:", "FADE IN"}:
                continue
            if _SECTION.match(line):
                in_cast_list = True
                continue
            heading = _SCENE_HEADING.match(line)
            if heading and not line.startswith("-") and not line.startswith("*"):
                in_cast_list = False
                title = _scene_title(heading.group(1))
                matched = self._match_scene(title, scenes) or default_scene
                if buckets[-1][1] or buckets[-1][0].id != matched.id:
                    buckets.append((matched, []))
                else:
                    buckets[-1] = (matched, [])
                continue
            if in_cast_list:
                continue
            if line.startswith("參考圖") or line.startswith("!["):
                continue
            buckets[-1][1].append(line)

        merged: list[tuple[Entity, list[str]]] = []
        for scene, beats in buckets:
            compact = self._compact_beats(beats)
            if compact or (merged and merged[-1][0].id != scene.id):
                merged.append((scene, compact))
        return merged or [(default_scene, [])]

    def _match_scene(self, title: str, scenes: list[Entity]) -> Entity | None:
        compact = re.sub(r"\s+", "", title)
        for scene in scenes:
            if re.sub(r"\s+", "", scene.name) in compact or compact in re.sub(r"\s+", "", scene.name):
                return scene
        return scenes[0] if scenes else None

    def _compact_beats(self, lines: list[str]) -> list[str]:
        beats: list[str] = []
        buf: list[str] = []
        for line in lines:
            if _is_zh_cue(line) or _is_en_cue(line):
                if buf:
                    beats.append(" ".join(buf))
                    buf = []
                buf.append(line)
                continue
            buf.append(line)
            joined = " ".join(buf)
            if len(joined) >= 24 or line.endswith("。") or line.endswith("."):
                beats.append(joined)
                buf = []
        if buf:
            beats.append(" ".join(buf))
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


def _is_zh_cue(line: str) -> bool:
    return bool(re.fullmatch(r"[\u4e00-\u9fff]{2,8}", line))


def _is_en_cue(line: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9 \-]{1,40}", line))


def director_node(state: AgentState) -> AgentState:
    return Director().direct(state)
