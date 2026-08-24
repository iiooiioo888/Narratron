"""敘事自舉：一句話 → 護照初稿、種子劇本、按需年齡曲線。"""

from __future__ import annotations

from narratron.agents.director import Director
from narratron.agents.parser import Parser
from narratron.agents.state import AgentState
from narratron.narrative.bootstrap import (
    bootstrap_from_brief,
    looks_like_character_brief,
    looks_like_screenplay,
    resolve_ensure_identity,
)
from narratron.narrative.world_bible import CYBERPUNK_CITY, STORYBOOK_KINGDOM, fit_world
from narratron.vault.schema import EntityKind

BRIEF = "一名年齡為8歲的小女孩，可愛風格，公主風"


def test_brief_is_not_treated_as_screenplay() -> None:
    assert looks_like_character_brief(BRIEF) is True
    assert looks_like_screenplay(BRIEF) is False
    assert looks_like_character_brief("莉娜站在雨中。") is False
    assert looks_like_screenplay("角色：\n- 安娜\n") is True


def test_bootstrap_princess_brief() -> None:
    result = bootstrap_from_brief(BRIEF)
    assert result.age == 8
    assert result.gender_spectrum == 0.0
    assert result.mbti == "ENFJ"
    assert result.world.id == STORYBOOK_KINGDOM.id
    assert result.physiology["weight_kg"] < 40
    assert result.physiology["height_cm"] < 150
    assert result.age_curve["present"] == 8
    assert result.age_curve["generate_now"] == [8]
    assert 18 in result.age_curve["keyframes"]
    assert result.age_curve["enqueue"] is False
    assert result.age_curve["span"] is False
    assert "極度害怕獨自過夜" in result.inner_flaw
    assert result.seed_script.count("極度害怕獨自過夜") == 1
    assert "不敢獨自過夜" not in result.seed_script
    assert "螢火蟲" in "".join(result.habits)
    assert "INT." in result.seed_script
    assert result.name in result.seed_script
    assert "extra fingers" in result.manifest["_constraints"]["must_never"]
    assert result.manifest["_identity"]["age_appearance"] == "8"


def test_same_brief_is_idempotent() -> None:
    first = bootstrap_from_brief(BRIEF)
    second = bootstrap_from_brief(BRIEF)
    assert first.name == second.name
    assert first.alias == second.alias
    assert first.inner_flaw == second.inner_flaw


def test_cyberpunk_world_fitting() -> None:
    result = bootstrap_from_brief("一名8歲小女孩，賽博朋克企業千金，可愛風格")
    assert result.world.id == CYBERPUNK_CITY.id
    assert "企業" in result.occupation or "千金" in result.occupation


def test_fit_world_defaults_to_storybook() -> None:
    assert fit_world(BRIEF).id == STORYBOOK_KINGDOM.id


def test_overrides_cascade_into_seed_script() -> None:
    result = bootstrap_from_brief(
        BRIEF,
        overrides={"name": "晨曦", "inner_flaw": "不敢踏進沒有燈光的走廊", "habits": ["會把 croissants 掰給鳥吃"]},
    )
    assert result.name == "晨曦"
    assert "不敢踏進沒有燈光的走廊" in result.inner_flaw
    assert "晨曦" in result.seed_script
    assert "croissants" in result.seed_script or "鳥" in "".join(result.habits)


def test_parser_inflates_brief_instead_of_untitled_scene_only() -> None:
    state = Parser(persist=False).parse(AgentState(script=BRIEF))
    names = {item.name for item in state.entities}
    assert state.bootstrap and state.bootstrap["active"] is True
    protagonist = state.bootstrap["character"]["name"]
    assert protagonist in names
    assert any(item.kind is EntityKind.SCENE and item.name != "未標場景" for item in state.entities)
    lead = next(item for item in state.entities if item.name == protagonist)
    assert isinstance(lead.payload.get("charpass"), dict)
    assert any(record.cause == "敘事自舉" for record in state.traces)
    assert "INT." in state.script


def test_director_splits_brief_into_real_shots() -> None:
    state = Director(persist=False).direct(AgentState(script=BRIEF))
    assert state.bootstrap and state.bootstrap["active"] is True
    assert len(state.shots) >= 3
    protagonist = state.bootstrap["character"]["name"]
    beats = [str(shot.payload.get("beat") or "") for shot in state.shots]
    assert any(protagonist in beat for beat in beats)
    ages = [
        shot.payload.get("visual_requirements", {}).get("variant_params", {}).get("age")
        for shot in state.shots
    ]
    assert 8 in ages
    assert all(shot.payload.get("generation_snapshot", {}).get("fallback") == "base_body" for shot in state.shots)
    assert all(
        shot.payload.get("visual_requirements", {}).get("generation_mode") == "lazy" for shot in state.shots
    )


def test_director_still_handles_regular_screenplay() -> None:
    script = """
角色：
- 莉娜

INT. 月台 - NIGHT
莉娜走上月台。她停在雨中。
""".strip()
    state = Director(persist=False).direct(AgentState(script=script))
    assert state.bootstrap is None
    assert [shot.payload["beat"] for shot in state.shots] == [
        "莉娜走上月台。",
        "她停在雨中。",
    ]


def test_resolve_ensure_identity_uses_generated_name() -> None:
    resolved = resolve_ensure_identity(BRIEF, base_age=25)
    assert resolved["name"] != BRIEF
    assert resolved["base_age"] == 8
    assert resolved["manifest"]["_identity"]["name"] == resolved["name"]
