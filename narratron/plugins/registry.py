"""P1–P13 註冊表：編號、代號、中文、觸發時機。"""

from __future__ import annotations

from narratron.naming import PLUGIN_MATRIX, TRIGGER_LABELS
from narratron.plugins.context import Plugin, TriggerPhase
from narratron.plugins.cropper import Cropper
from narratron.plugins.exporter import Exporter
from narratron.plugins.filter import Filter
from narratron.plugins.fixer import Fixer
from narratron.plugins.forker import Forker
from narratron.plugins.maker import Maker
from narratron.plugins.mover import Mover
from narratron.plugins.painter import Painter
from narratron.plugins.player import Player
from narratron.plugins.recycler import Recycler
from narratron.plugins.router import Router
from narratron.plugins.screener import Screener
from narratron.plugins.tracer import Tracer

_TRIGGER_MAP: dict[str, tuple[TriggerPhase, ...]] = {
    "pre": (TriggerPhase.PRE,),
    "post": (TriggerPhase.POST,),
    "pre_post": (TriggerPhase.PRE, TriggerPhase.POST),
}

PLUGIN_CLASSES: dict[str, type[Plugin]] = {
    "Tracer": Tracer,
    "Fixer": Fixer,
    "Forker": Forker,
    "Painter": Painter,
    "Mover": Mover,
    "Screener": Screener,
    "Router": Router,
    "Recycler": Recycler,
    "Player": Player,
    "Filter": Filter,
    "Cropper": Cropper,
    "Exporter": Exporter,
    "Maker": Maker,
}


def trigger_key(triggers: tuple[TriggerPhase, ...]) -> str:
    has_pre = TriggerPhase.PRE in triggers
    has_post = TriggerPhase.POST in triggers
    if has_pre and has_post:
        return "pre_post"
    if has_post:
        return "post"
    return "pre"


def iter_plugins() -> list[Plugin]:
    return [cls() for cls in PLUGIN_CLASSES.values()]


def expected_matrix() -> tuple[tuple[str, str, str, str, str], ...]:
    return PLUGIN_MATRIX


__all__ = [
    "PLUGIN_CLASSES",
    "PLUGIN_MATRIX",
    "TRIGGER_LABELS",
    "expected_matrix",
    "iter_plugins",
    "trigger_key",
    "_TRIGGER_MAP",
]
