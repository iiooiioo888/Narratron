"""Parser：劇本 → 角色 / 道具 / 場景 + Trace Log + 參考圖資產。"""

from __future__ import annotations

from pathlib import Path

from narratron.agents.parser import Parser
from narratron.agents.state import AgentState
from narratron.vault.memory import InMemoryStore
from narratron.vault.schema import EntityKind
from narratron.vault.state_vault import StateVault

FIXTURE = Path(__file__).parent / "fixtures" / "sample_script.txt"


def test_parser_extracts_trinity_cast() -> None:
    store = InMemoryStore()
    vault = StateVault(store)
    script = FIXTURE.read_text(encoding="utf-8")
    state = Parser(vault=vault).parse(AgentState(script=script))

    names = {item.name for item in state.entities}
    assert "莉娜" in names
    assert "卡爾" in names
    assert "鏽鑰匙" in names
    assert "舊繃帶" in names
    assert any(item.kind is EntityKind.SCENE and item.name == "廢墟教堂" for item in state.entities)
    assert sum(1 for item in state.entities if item.kind is EntityKind.SCENE) == 1

    lina = next(item for item in state.entities if item.name == "莉娜")
    assert "scar" in lina.payload["continuity_tokens"]
    assert "bandage" in lina.payload["continuity_tokens"]

    key = next(item for item in state.entities if item.name == "鏽鑰匙")
    assert "rust" in key.payload["continuity_tokens"]
    assert "wear" in key.payload["continuity_tokens"]

    assert vault.get_entities()
    assert any(record.cause == "劇本揭示" for record in vault.get_traces())
    assert any(asset.kind == "reference_image" for asset in vault.get_assets())
    assert any(asset.kind == "ip_adapter_finetune" for asset in vault.get_assets())
    job = next(asset for asset in vault.get_assets() if asset.kind == "ip_adapter_finetune")
    assert job.metadata["status"] == "queued"


def test_parser_without_persist_does_not_need_vault() -> None:
    state = Parser(persist=False).parse(AgentState(script="角色：\n- 安娜\n"))
    assert any(item.name == "安娜" for item in state.entities)
    assert state.traces


def test_parser_does_not_invent_characters_from_action_lines() -> None:
    script = """
莉娜走進廢棄工廠
她停在鐵門前
卡爾從陰影裡走出來
兩人對視
莉娜說我們該走了
""".strip()
    state = Parser(persist=False).parse(AgentState(script=script))
    names = {item.name for item in state.entities if item.kind is EntityKind.CHARACTER}
    assert "莉娜" in names
    assert "卡爾" in names
    assert "她停在鐵門前" not in names
    assert "兩人對視" not in names
