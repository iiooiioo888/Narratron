"""API 閘道路由。Alpha Q1：/parse 與 /direct 可跑；其餘生成路由 501。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from narratron import SLOGAN, VERSION
from narratron.agents.director import Director
from narratron.agents.parser import Parser
from narratron.agents.state import AgentState
from narratron.api.characters import v1_router
from narratron.api.settings import get_settings
from narratron.naming import PLATFORM
from narratron.vault.state_vault import StateVault, get_default_vault

router = APIRouter()
router.include_router(v1_router, prefix="/api/v1")


class HealthResponse(BaseModel):
    status: str
    platform: str
    version: str
    slogan: str
    vault_backend: str
    phase: str


class ScriptPayload(BaseModel):
    script: str = Field(min_length=1)
    persist: bool = True


def _vault() -> StateVault:
    return get_default_vault()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        platform=PLATFORM,
        version=VERSION,
        slogan=SLOGAN,
        vault_backend=settings.vault_backend,
        phase="Alpha Q1",
    )


@router.get("/characteros/panel")
def characteros_panel() -> RedirectResponse:
    """總系統入口：轉址到 CharacterOS GUI 編輯面板。"""
    settings = get_settings()
    return RedirectResponse(url=settings.characteros_panel_url, status_code=307)


def _not_implemented(agent: str, quarter: str) -> None:
    raise HTTPException(
        status_code=501,
        detail=f"{agent} 實作待 {quarter}；禁止在本階段跑生成。",
    )


@router.post("/parse")
def parse(payload: ScriptPayload) -> dict[str, Any]:
    vault = _vault() if payload.persist else None
    state = Parser(vault=vault, persist=payload.persist).parse(AgentState(script=payload.script))
    return state.model_dump(mode="json")


@router.post("/direct")
def direct(payload: ScriptPayload) -> dict[str, Any]:
    vault = _vault() if payload.persist else None
    parser = Parser(vault=vault, persist=payload.persist)
    state = Director(vault=vault, persist=payload.persist, parser=parser).direct(
        AgentState(script=payload.script)
    )
    return state.model_dump(mode="json")


@router.post("/keep")
def keep(payload: ScriptPayload) -> None:
    _ = payload
    _not_implemented("Keeper", "Alpha Q2")


@router.post("/run")
def run(payload: ScriptPayload) -> None:
    _ = payload
    _not_implemented("Runner", "Alpha Q3")


@router.post("/mux")
def mux(payload: ScriptPayload) -> None:
    _ = payload
    _not_implemented("Muxer", "Alpha Q4")
