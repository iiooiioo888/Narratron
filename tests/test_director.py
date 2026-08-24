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


def test_director_keeps_body_after_metadata_lists() -> None:
    """前端範例格式的 metadata 清單不可吞掉後續對白。"""
    script = """
INT. 廢棄工廠 — 夜

角色
- 卡爾（傷疤覆蓋左臉）
- 艾拉（繃帶纏繞右臂）

道具
- 無線電

場景
- 廢棄工廠：昏暗的吊燈搖晃

卡爾：（壓低聲音）守衛換班了，我們有十分鐘。
艾拉：（檢查無線電）信號很弱，但夠用！
""".strip()

    state = Director(persist=False).direct(AgentState(script=script))

    beats = [str(shot.payload.get("beat", "")) for shot in state.shots]
    assert len(state.shots) == 2
    assert any("守衛換班了" in beat for beat in beats)
    assert any("信號很弱" in beat for beat in beats)
    assert all("傷疤覆蓋左臉" not in beat for beat in beats)
    assert all("昏暗的吊燈" not in beat for beat in beats)


def test_director_does_not_treat_named_action_as_dialogue() -> None:
    script = """
角色：
- 莉娜
- 卡爾

INT. 廢墟教堂 - NIGHT
祭壇上的燭火忽明忽暗。
莉娜走向祭壇。
""".strip()

    state = Director(persist=False).direct(AgentState(script=script))

    assert len(state.shots) == 2
    assert state.shots[1].camera_language == "跟拍 Tracking"


def test_director_splits_multiple_action_sentences_into_shots() -> None:
    script = """
角色：
- 莉娜

INT. 月台 - NIGHT
莉娜走上月台。她停在雨中。她回頭望向空車廂。
""".strip()

    state = Director(persist=False).direct(AgentState(script=script))

    assert [shot.payload["beat"] for shot in state.shots] == [
        "莉娜走上月台。",
        "她停在雨中。",
        "她回頭望向空車廂。",
    ]


def test_director_emits_lazy_multidimensional_visual_requirements() -> None:
    script = """
角色：
- 莉娜：左頰舊傷痕

場景：
- 廢墟教堂：雨夜

INT. 廢墟教堂 - NIGHT
25 歲的莉娜悲傷地站在雨中，手臂正在流血。
""".strip()

    state = Director(persist=False).direct(AgentState(script=script))

    requirements = state.shots[0].payload["visual_requirements"]
    assert requirements["character_ids"] == ["character-莉娜"]
    assert requirements["variant_params"] == {
        "age": 25,
        "emotion": "sad",
        "scene": "廢墟教堂",
        "weather": "rain",
        "injury": 0.7,
    }
    assert requirements["age_plan"] == {
        "target": 25,
        "anchors": [18, 30],
        "blend": 0.5833,
        "method": "latent_interpolation",
    }
    assert requirements["generation_mode"] == "lazy"
    assert requirements["enqueue"] is False
    assert requirements["identity_anchor"] == {"required": True, "source": "charpass"}
    assert requirements["keyframe"] is True
    assert requirements["render_tier"] == "final"
    assert len(requirements["cache_key"]) == 64
    assert state.shots[0].payload["generation_snapshot"]["fallback"] == "base_body"


def test_director_keeps_speaker_on_multiline_dialogue() -> None:
    script = """
角色：
- 莉娜

INT. 月台 - NIGHT
莉娜
你終於來了。
我等了整整三年。

遠處的列車駛入月台。
""".strip()

    state = Director(persist=False).direct(AgentState(script=script))

    beats = [shot.payload["beat"] for shot in state.shots]
    assert beats == [
        "莉娜 你終於來了。",
        "莉娜 我等了整整三年。",
        "遠處的列車駛入月台。",
    ]
    assert state.shots[1].camera_language == "特寫 Close-up"
    assert state.shots[2].camera_language != "特寫 Close-up"


def test_director_splits_colon_action_without_inventing_speaker() -> None:
    script = """
INT. 倉庫 - NIGHT
牆上時鐘：午夜十二點。鐵門突然打開。
""".strip()

    state = Director(persist=False).direct(AgentState(script=script))

    assert [shot.payload["beat"] for shot in state.shots] == [
        "牆上時鐘：午夜十二點。",
        "鐵門突然打開。",
    ]


def test_director_splits_inline_dialogue_and_keeps_speaker() -> None:
    script = """
角色：
- 卡爾

INT. 控制室 - NIGHT
卡爾：先切斷電源。然後立刻離開！
""".strip()

    state = Director(persist=False).direct(AgentState(script=script))

    assert [shot.payload["beat"] for shot in state.shots] == [
        "卡爾：先切斷電源。",
        "卡爾：然後立刻離開！",
    ]
    assert state.shots[1].camera_language == "特寫 Close-up"


def test_director_carries_character_identity_across_pronoun_shots() -> None:
    script = """
角色：
- 莉娜
- 卡爾

INT. 月台 - NIGHT
莉娜走上月台。她停在雨中。她回頭望向空車廂。
""".strip()

    state = Director(persist=False).direct(AgentState(script=script))

    requirements = [shot.payload["visual_requirements"] for shot in state.shots]
    assert [item["character_ids"] for item in requirements] == [
        ["character-莉娜"],
        ["character-莉娜"],
        ["character-莉娜"],
    ]
    assert len({item["variant_cache_key"] for item in requirements}) == 2
    assert len({item["cache_key"] for item in requirements}) == 3


def test_director_camera_uses_characters_in_current_beat_not_global_cast() -> None:
    script = """
角色：
- 莉娜
- 卡爾
- 艾拉

INT. 月台 - NIGHT
月台空無一人。
遠處的列車鳴笛。
""".strip()

    state = Director(persist=False).direct(AgentState(script=script))

    assert state.shots[1].camera_language == "中景 Medium"
    assert state.shots[1].payload["visual_requirements"]["character_ids"] == []


def test_director_visual_cache_changes_with_charpass_profile_revision() -> None:
    base_script = """
角色：
- 莉娜

INT. 月台 - NIGHT
30 歲的莉娜站在月台。
""".strip()
    parsed = Parser(persist=False).parse(AgentState(script=base_script))
    character = next(item for item in parsed.entities if item.name == "莉娜")
    character.payload["charpass"] = {
        "_meta": {"profile_version": 1},
        "_identity": {"name": "莉娜", "face_id": "face-a"},
    }
    first = Director(persist=False).direct(parsed)

    character.payload["charpass"]["_meta"]["profile_version"] = 2
    second = Director(persist=False).direct(parsed)

    first_visual = first.shots[0].payload["visual_requirements"]
    second_visual = second.shots[0].payload["visual_requirements"]
    assert first_visual["profile_revisions"][0]["profile_version"] == 1
    assert second_visual["profile_revisions"][0]["profile_version"] == 2
    assert first_visual["variant_cache_key"] != second_visual["variant_cache_key"]


def test_director_splits_unpunctuated_action_lines() -> None:
    """中文分鏡常以換行當一句，不可因沒有句號而被併成一鏡。"""
    script = """
角色：
- 莉娜
- 卡爾

INT. 廢棄工廠 - NIGHT
莉娜走進廢棄工廠
她停在鐵門前
卡爾從陰影裡走出來
兩人對視
莉娜：我們該走了
""".strip()

    state = Director(persist=False).direct(AgentState(script=script))
    beats = [str(shot.payload.get("beat") or "") for shot in state.shots]
    assert beats == [
        "莉娜走進廢棄工廠",
        "她停在鐵門前",
        "卡爾從陰影裡走出來",
        "兩人對視",
        "莉娜：我們該走了",
    ]
    ids = [shot.payload["visual_requirements"]["character_ids"] for shot in state.shots]
    assert ids[0] == ["character-莉娜"]
    assert ids[1] == ["character-莉娜"]
    assert ids[2] == ["character-卡爾"]
    assert ids[4] == ["character-莉娜"]


def test_director_keeps_ellipsis_dialogue_as_one_shot() -> None:
    script = """
角色：
- 艾莉絲

INT. 晨露城堡 寢宮 - NIGHT
艾莉絲
今晚……可以留下一盞燈嗎？
""".strip()

    state = Director(persist=False).direct(AgentState(script=script))
    assert [shot.payload["beat"] for shot in state.shots] == [
        "艾莉絲 今晚……可以留下一盞燈嗎？",
    ]


def test_director_inherits_passport_age_without_forcing_keyframe() -> None:
    script = """
角色：
- 莉娜

INT. 月台 - NIGHT
莉娜走上月台。
""".strip()
    parsed = Parser(persist=False).parse(AgentState(script=script))
    character = next(item for item in parsed.entities if item.name == "莉娜")
    character.payload["charpass"] = {
        "_meta": {"profile_version": 1},
        "_identity": {"name": "莉娜", "age_appearance": "8"},
    }
    state = Director(persist=False).direct(parsed)
    visual = state.shots[0].payload["visual_requirements"]
    assert visual["variant_params"]["age"] == 8
    assert visual["keyframe"] is True
    assert visual["age_plan"]["target"] == 8

    follow = """
角色：
- 莉娜

INT. 月台 - NIGHT
月台空無一人。
莉娜走上月台。
""".strip()
    parsed = Parser(persist=False).parse(AgentState(script=follow))
    character = next(item for item in parsed.entities if item.name == "莉娜")
    character.payload["charpass"] = {
        "_meta": {"profile_version": 1},
        "_identity": {"name": "莉娜", "age_appearance": "8"},
    }
    state = Director(persist=False).direct(parsed)
    establishing = state.shots[0].payload["visual_requirements"]
    follow_visual = state.shots[1].payload["visual_requirements"]
    assert establishing["keyframe"] is True
    assert follow_visual["variant_params"]["age"] == 8
    assert follow_visual["keyframe"] is False
    assert follow_visual["render_tier"] == "draft"
