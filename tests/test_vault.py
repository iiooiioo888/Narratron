"""State Vault / Trace Log / Chroma / Redis 記憶體後端。"""

from __future__ import annotations

from narratron.vault.chroma import Chroma
from narratron.vault.memory import InMemoryStore
from narratron.vault.redis_cache import Redis
from narratron.vault.schema import Entity, EntityKind, Shot, TraceRecord
from narratron.vault.state_vault import StateVault


def test_vault_roundtrip_and_trace_log() -> None:
    vault = StateVault(InMemoryStore())
    entity = Entity(id="character-lina", kind=EntityKind.CHARACTER, name="莉娜", payload={"scar": True})
    vault.init_from_parser([entity])
    vault.upsert_shots(
        [Shot(id="shot-0001", scene_id="scene-chapel", order=1, camera_language="全景 Establishing")]
    )
    vault.register_reference_image(asset_id="asset-1", uri="file://refs/lina.png", entity_id=entity.id)
    vault.trace_log().append(
        TraceRecord(id="t1", entity_id=entity.id, shot_id="shot-0001", cause="創傷", effect="退縮")
    )

    assert vault.get_entities()[0].name == "莉娜"
    assert vault.get_shots()[0].id == "shot-0001"
    assert vault.get_assets()[0].kind == "reference_image"
    traces = vault.trace_log().list_for_entity("character-lina")
    assert traces[0].effect == "退縮"
    assert vault.trace_log().list_for_shot("shot-0001")


def test_chroma_and_redis_memory() -> None:
    chroma = Chroma()
    chroma.upsert(["character-lina"], ["莉娜 左頰傷痕"], [{"kind": "character"}])
    hits = chroma.query("傷痕")
    assert hits and hits[0]["id"] == "character-lina"

    cache = Redis()
    cache.set("shot:1", b"ok", ttl_seconds=60)
    assert cache.get("shot:1") == b"ok"
