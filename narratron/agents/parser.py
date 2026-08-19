"""Parser（解析器）：讀取劇本，提取角色、道具、場景，初始化 State Vault。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable

from narratron.agents.state import AgentState
from narratron.charpass.vault_bridge import project_tokens_into_charpass
from narratron.vault.chroma import Chroma
from narratron.vault.schema import Asset, Entity, EntityKind, TraceRecord
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
_NAME_SPLIT = re.compile(r"[、,，/|｜]+")
_TRAIT_SEP = re.compile(r"[：:｜|]")
_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_REF_LINE = re.compile(r"^參考圖[：:]\s*(.+)$")
_PROP_HOLD = re.compile(
    r"(?:握著|拿著|拿出|拿起|舉起|持|holds?|holding)\s*[「『\"']?([^」』\"'，。\s]{2,16})"
)
_EN_CUE = re.compile(r"^[A-Z][A-Z0-9 \-]{1,40}$")
_ZH_CUE = re.compile(r"^[\u4e00-\u9fff]{2,8}$")
_ZH_DIALOGUE = re.compile(r"^([\u4e00-\u9fff]{2,8})[：:](.+)$")
_CONTINUITY = (
    (re.compile(r"傷痕|傷口|疤|scar", re.I), "scar"),
    (re.compile(r"繃帶|绷带|bandage", re.I), "bandage"),
    (re.compile(r"鏽|锈|rust", re.I), "rust"),
    (re.compile(r"磨損|磨损|worn|wear", re.I), "wear"),
    (re.compile(r"滲血|渗血|blood", re.I), "bloodstain"),
)

_SECTION_KIND = {
    "角色": EntityKind.CHARACTER,
    "人物": EntityKind.CHARACTER,
    "character": EntityKind.CHARACTER,
    "characters": EntityKind.CHARACTER,
    "道具": EntityKind.PROP,
    "prop": EntityKind.PROP,
    "props": EntityKind.PROP,
    "場景": EntityKind.SCENE,
    "scene": EntityKind.SCENE,
    "scenes": EntityKind.SCENE,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


_TIME_OF_DAY = re.compile(r"\s+(NIGHT|DAY|DAWN|DUSK|EVENING|MORNING|夜|日|晨|黃昏)\s*$", re.I)


def _scene_title(raw: str) -> str:
    title = re.sub(r"\s*[-–—]\s*", " ", raw.strip())
    title = _TIME_OF_DAY.sub("", title).strip()
    return title or raw.strip()


def _slug(kind: EntityKind, name: str) -> str:
    compact = re.sub(r"\s+", "-", name.strip())
    compact = re.sub(r"[^\w\-一-龥]", "", compact)
    if not compact:
        compact = "unnamed"
    return f"{kind.value}-{compact}"[:96]


def _continuity_tokens(*texts: str) -> list[str]:
    blob = " ".join(texts)
    found: list[str] = []
    for pattern, token in _CONTINUITY:
        if pattern.search(blob) and token not in found:
            found.append(token)
    return found


def _split_names(raw: str) -> list[str]:
    parts = [part.strip() for part in _NAME_SPLIT.split(raw) if part.strip()]
    return parts or ([raw.strip()] if raw.strip() else [])


def _parse_named_item(raw: str) -> tuple[str, str]:
    pieces = [part.strip() for part in _TRAIT_SEP.split(raw, maxsplit=1)]
    name = pieces[0].strip(" （()）")
    note = pieces[1] if len(pieces) > 1 else ""
    if "（" in name:
        name, rest = name.split("（", 1)
        note = (rest.rstrip("）") + ("；" + note if note else "")).strip("；")
        name = name.strip()
    return name, note


class Parser:
    def __init__(
        self,
        vault: StateVault | None = None,
        *,
        persist: bool = True,
        chroma: Chroma | None = None,
    ) -> None:
        self._persist = persist
        self._vault = vault
        self._chroma = chroma if chroma is not None else Chroma()

    def _vault_or_default(self) -> StateVault | None:
        if not self._persist:
            return self._vault
        return self._vault if self._vault is not None else get_default_vault()

    def parse(self, state: AgentState) -> AgentState:
        entities, traces, assets = self.extract(state.script)
        vault = self._vault_or_default()
        if vault is not None:
            entities = [self._merge_vault_charpass(vault, item) for item in entities]
            vault.init_from_parser(entities)
            vault.upsert_assets(assets)
            vault.trace_log().append_many(traces)
            self._index_entities(entities)
            if assets:
                from narratron.models.flux import queue_ip_adapter_finetune

                job = queue_ip_adapter_finetune(vault, assets)
                assets = [*assets, job]
        return state.model_copy(
            update={
                "entities": entities,
                "traces": traces,
                "assets": assets,
            }
        )

    def extract(self, script: str) -> tuple[list[Entity], list[TraceRecord], list[Asset]]:
        by_id: dict[str, Entity] = {}
        assets: list[Asset] = []
        section: EntityKind | None = None
        lines = script.replace("\r\n", "\n").split("\n")

        for index, raw in enumerate(lines):
            line = raw.strip()
            if not line or line.upper() in {"FADE IN:", "FADE IN", "FADE OUT.", "FADE OUT"}:
                if not line:
                    section = None if section is EntityKind.SCENE else section
                continue

            image_match = _IMAGE.search(line)
            if image_match:
                uri = image_match.group(1).strip()
                assets.append(
                    Asset(
                        id=f"asset-ref-{len(assets)+1}",
                        kind="reference_image",
                        uri=uri,
                        metadata={"source": "script"},
                    )
                )
                continue

            ref_match = _REF_LINE.match(line)
            if ref_match:
                uri = ref_match.group(1).strip()
                assets.append(
                    Asset(
                        id=f"asset-ref-{len(assets)+1}",
                        kind="reference_image",
                        uri=uri,
                        metadata={"source": "script"},
                    )
                )
                continue

            section_match = _SECTION.match(line)
            if section_match:
                section = _SECTION_KIND[section_match.group(1).lower()]
                continue

            inline = _INLINE_SECTION.match(line)
            if inline:
                kind = _SECTION_KIND[inline.group(1).lower()]
                for chunk in _split_names(inline.group(2)):
                    self._put_entity(by_id, kind, *self._named(chunk))
                section = None
                continue

            heading = _SCENE_HEADING.match(line)
            if heading and not _LIST_ITEM.match(line):
                title = _scene_title(heading.group(1))
                self._put_entity(by_id, EntityKind.SCENE, title, line)
                section = None
                continue

            listed = _LIST_ITEM.match(line)
            if listed and section is not None:
                self._put_entity(by_id, section, *self._named(listed.group(1)))
                continue

            dialogue = _ZH_DIALOGUE.match(line)
            if dialogue:
                self._put_entity(by_id, EntityKind.CHARACTER, dialogue.group(1), dialogue.group(2))
                continue

            nxt = lines[index + 1].strip() if index + 1 < len(lines) else ""
            if self._is_character_cue(line, nxt):
                self._put_entity(by_id, EntityKind.CHARACTER, line, nxt)
                continue

            for held in _PROP_HOLD.findall(line):
                self._put_entity(by_id, EntityKind.PROP, held, line)

        if not any(item.kind is EntityKind.SCENE for item in by_id.values()):
            self._put_entity(by_id, EntityKind.SCENE, "未標場景", "default-scene")

        entities = list(by_id.values())
        traces = [
            TraceRecord(
                id=f"trace-init-{entity.id}",
                entity_id=entity.id,
                cause="劇本揭示",
                effect=f"{entity.name} 進入 State Vault",
                happened_at=_now(),
                payload={
                    "kind": entity.kind.value,
                    "continuity_tokens": entity.payload.get("continuity_tokens", []),
                },
            )
            for entity in entities
        ]
        return entities, traces, assets

    def _named(self, raw: str) -> tuple[str, str]:
        return _parse_named_item(raw)

    def _merge_vault_charpass(self, vault: StateVault, entity: Entity) -> Entity:
        existing = vault.get_entity(entity.id)
        if existing is None:
            return entity
        payload = dict(entity.payload)
        for key, value in existing.payload.items():
            if key in {"note", "continuity_tokens"}:
                continue
            payload.setdefault(key, value)
        passport = existing.payload.get("charpass")
        if isinstance(passport, dict):
            payload["charpass"] = project_tokens_into_charpass(
                passport,
                payload.get("continuity_tokens") or [],
            )
        entity.payload = payload
        return entity

    def _put_entity(
        self,
        by_id: dict[str, Entity],
        kind: EntityKind,
        name: str,
        note: str = "",
    ) -> None:
        name = name.strip()
        if not name:
            return
        entity_id = _slug(kind, name)
        tokens = _continuity_tokens(name, note)
        existing = by_id.get(entity_id)
        if existing is None:
            by_id[entity_id] = Entity(
                id=entity_id,
                kind=kind,
                name=name,
                payload={
                    "note": note,
                    "continuity_tokens": tokens,
                },
                created_at=_now(),
            )
            return
        merged_note = existing.payload.get("note") or ""
        if note and note not in merged_note:
            merged_note = f"{merged_note}；{note}".strip("；")
        merged_tokens = list(existing.payload.get("continuity_tokens") or [])
        for token in tokens:
            if token not in merged_tokens:
                merged_tokens.append(token)
        existing.payload["note"] = merged_note
        existing.payload["continuity_tokens"] = merged_tokens
        passport = existing.payload.get("charpass")
        if isinstance(passport, dict):
            existing.payload["charpass"] = project_tokens_into_charpass(passport, merged_tokens)

    def _is_character_cue(self, line: str, nxt: str) -> bool:
        if _EN_CUE.fullmatch(line):
            return True
        if _ZH_CUE.fullmatch(line) and nxt and not _SCENE_HEADING.match(nxt) and not _SECTION.match(nxt):
            return True
        return False

    def _index_entities(self, entities: Iterable[Entity]) -> None:
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, str]] = []
        for entity in entities:
            ids.append(entity.id)
            documents.append(f"{entity.name} {entity.payload.get('note', '')}")
            metadatas.append({"kind": entity.kind.value, "name": entity.name})
        if ids:
            self._chroma.upsert(ids, documents, metadatas)


def parser_node(state: AgentState) -> AgentState:
    return Parser().parse(state)
