"""用戶層 GUI：五畫面凍結名、門面靜態檔、閘道 CORS。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from characteros.main import app as characteros_app
from narratron.api.app import app as gateway_app

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SCREENS = ("GraphView", "CausalGraph", "ScriptBox")


def test_facade_uses_frozen_screen_names() -> None:
    html = (ROOT / "characteros/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "characteros/static/js/gui.js").read_text(encoding="utf-8")
    css = (ROOT / "characteros/static/css/gui.css").read_text(encoding="utf-8")
    assert css
    for name in ("Pad", "Timeline", "Dashboard", "Map", "Player"):
        assert f'data-page="{name}"' in html
        assert f"id=\"page-{name}\"" in html
        assert name in js
    assert 'data-page="home"' not in html
    assert "Direct 拆分鏡" in html
    assert "從劇本同步" in html
    assert 'id="genLive"' in html
    assert "refreshGenerationFeedback" in js
    assert "charImageGallery" in html or "loadCharImageGallery" in js
    assert "sync-from-script" in js
    assert 'location.hash.slice(1) || "Pad"' in js
    for bad in FORBIDDEN_SCREENS:
        assert bad not in html
        assert bad not in js


def test_panel_html_is_extracted() -> None:
    panel = ROOT / "characteros/static/panel.html"
    assert panel.is_file()
    text = panel.read_text(encoding="utf-8")
    assert "CharacterOS 管理面板" in text
    py = (ROOT / "characteros/routers/panel.py").read_text(encoding="utf-8")
    assert "panel.html" in py
    assert "return \"\"\"<!doctype" not in py


def test_facade_and_panel_routes() -> None:
    client = TestClient(characteros_app)
    home = client.get("/")
    assert home.status_code == 200
    assert 'data-page="Pad"' in home.text
    assert "/static/js/gui.js" in home.text

    panel = client.get("/admin/panel")
    assert panel.status_code == 200
    assert "CharacterOS 管理面板" in panel.text
    assert "Pad / Timeline / Dashboard / Map / Player" in panel.text


def test_queue_worker_status_exposes_live_fields() -> None:
    client = TestClient(characteros_app)
    response = client.get("/api/v1/admin/queue-worker")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "busy" in body
    assert "running_count" in body
    assert "current_task" in body
    assert "pending_count" in body
    client = TestClient(gateway_app)
    response = client.get("/health", headers={"Origin": "http://localhost:8001"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:8001"


def test_webapp_keeps_five_screens_and_player() -> None:
    src = (ROOT / "frontend/webapp/src/App.tsx").read_text(encoding="utf-8")
    assert "PAGE_ORDER: PageId[] = ['Pad', 'Timeline', 'Dashboard', 'Map', 'Player']" in src
    assert "Big Core" in src
    assert "Mid Core" in src
    assert "Muxer 尚未上線" in src
    assert "CharpassPanel" in src
