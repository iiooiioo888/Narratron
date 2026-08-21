"""CharacterOS GUI 管理面板。"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Panel"])

_PANEL_HTML = Path(__file__).resolve().parents[1] / "static" / "panel.html"


@router.get("/admin/panel", response_class=HTMLResponse)
def get_admin_panel() -> HTMLResponse:
    """提供角色 GUI 管理/生成面板。"""
    if _PANEL_HTML.is_file():
        return HTMLResponse(content=_PANEL_HTML.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="<h1>CharacterOS 管理面板缺失</h1><p>請確認 characteros/static/panel.html 存在。</p>",
        status_code=500,
    )
