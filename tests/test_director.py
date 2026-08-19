"""Director：實體 → 分鏡與鏡頭語言，寫入 shots + Trace Log。"""

from __future__ import annotations

from pathlib import Path

from narratron.agents.director import Director
from narratron.agents.parser import Parser
from narratron.agents.state import AgentState
from narratron.vault.memory import InMemoryStore
from narratron.vault.state_vault import StateVault

FIXTURE = Path(__file__).parent / "fixtures" / "sample_script.txt"


def test_director_breaks_into_ordered_shots() -> None:
    store = InMemoryStore()
    vault = StateVault(store)
    script = FIXTURE.read_text(encoding="utf-8")
    parser = Parser(vault=vault)
    state = Director(vault=vault, parser=parser).direct(AgentState(script=script))

    assert state.shots
    assert [shot.order for shot in state.shots] == list(range(1, len(state.shots) + 1))
    assert state.shots[0].camera_language == "全景 Establishing"
    assert all(shot.scene_id for shot in state.shots)
    assert all(shot.duration_ms >= 1500 for shot in state.shots)
    assert vault.get_shots()
    assert any(record.shot_id for record in vault.get_traces())
    assert any("特寫" in shot.camera_language or "中景" in shot.camera_language for shot in state.shots[1:])


def test_director_tracks_on_movement_when_multiple_characters() -> None:
    """
    When the cast has multiple characters, older logic may prefer
    "過肩 Over-the-shoulder" even if the beat clearly contains movement verbs.
    """
    store = InMemoryStore()
    vault = StateVault(store)

    # Note: the action sentence intentionally does NOT include any character names.
    # This ensures `speaking=False`, so we can validate the camera decision order.
    script = """
角色：
- 莉娜：左頰舊傷痕，右腕繃帶
- 卡爾：沉默的向導

場景：
- 廢墟教堂：夜、雨後、碎玻璃

FADE IN:

INT. 廢墟教堂 - NIGHT

莉娜
我們不該回來。

自陰影走出，靴底碾過碎玻璃。
""".strip()

    parser = Parser(vault=vault)
    state = Director(vault=vault, parser=parser).direct(AgentState(script=script))

    assert len(state.shots) >= 2
    assert state.shots[0].camera_language == "全景 Establishing"
    assert state.shots[1].camera_language == "跟拍 Tracking"
