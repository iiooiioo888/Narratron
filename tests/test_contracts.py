"""契約層測試：import、Router 預設中核、一致性腳本。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from narratron.agents.state import AgentState
from narratron.api.app import app
from narratron.core import CausalLink, Compressor, LogicCore
from narratron.hardware.pools import HardwarePool
from narratron.naming import CHARACTEROS, CHARACTEROS_MODULES
from narratron.plugins.context import PluginContext, TriggerPhase
from narratron.plugins.router import Router
from narratron.plugins.tracer import Tracer
from scripts.check_consistency import main as check_main


def test_consistency_script_passes() -> None:
    assert check_main() == 0


def test_characteros_frozen_paths() -> None:
    code, zh, package, main = CHARACTEROS
    assert code == "CharacterOS"
    assert zh == "角色控制子系統"
    assert package == "characteros/"
    assert main == "characteros/main.py"
    root = Path(__file__).resolve().parents[1]
    for rel in CHARACTEROS_MODULES:
        assert (root / rel).is_file(), rel
        assert "character_service" not in rel
        assert "hash_utils" not in rel
        assert "_manager" not in rel
        assert "_engine" not in rel
        assert "schemas.py" not in rel


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["platform"] == "Narratron"
    assert body["slogan"] == "Every Frame Carries Its Past."
    assert body["phase"] == "Alpha Q1"


def test_characteros_panel_redirect() -> None:
    client = TestClient(app)
    response = client.get("/characteros/panel", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost:8001/admin/panel"


def test_parse_and_direct_routes() -> None:
    client = TestClient(app)
    script = "角色：\n- 莉娜：傷痕\n\nINT. 廢墟 - NIGHT\n莉娜站著。\n"
    parsed = client.post("/parse", json={"script": script, "persist": False})
    assert parsed.status_code == 200, parsed.text
    body = parsed.json()
    assert any(item["name"] == "莉娜" for item in body["entities"])

    directed = client.post("/direct", json={"script": script, "persist": False})
    assert directed.status_code == 200, directed.text
    shots = directed.json()["shots"]
    assert shots
    assert shots[0]["camera_language"].startswith("全景")


def test_generate_routes_are_501() -> None:
    client = TestClient(app)
    for path in ("/keep", "/run", "/mux"):
        response = client.post(path, json={"script": "FADE IN"})
        assert response.status_code == 501, path


def test_router_returns_mid_core() -> None:
    result = Router().run(PluginContext(shot_id="s1", phase=TriggerPhase.PRE))
    assert result.passed is True
    assert result.metadata["pool"] == HardwarePool.L1.value
    assert result.metadata["code"] == "Mid Core"


def test_tracer_is_stub() -> None:
    try:
        Tracer().run(PluginContext(shot_id="s1", phase=TriggerPhase.PRE))
    except NotImplementedError as exc:
        assert "Tracer" in str(exc)
    else:
        raise AssertionError("Tracer 不應在本階段實作")


def test_trinity_and_state_defaults() -> None:
    assert LogicCore.__name__ == "LogicCore"
    assert CausalLink.__name__ == "CausalLink"
    assert Compressor.__name__ == "Compressor"
    state = AgentState()
    assert state.selected_pool is HardwarePool.L1
    assert state.entities == []
