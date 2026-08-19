"""Plug-in Bus：依觸發時機分派至 P1–P13。"""

from __future__ import annotations

from narratron.plugins.context import Plugin, PluginContext, PluginResult, TriggerPhase
from narratron.plugins.registry import iter_plugins


class PluginBus:
    def __init__(self, plugins: list[Plugin] | None = None) -> None:
        self._plugins = plugins if plugins is not None else iter_plugins()

    def dispatch(self, phase: TriggerPhase, context: PluginContext) -> list[PluginResult]:
        results: list[PluginResult] = []
        bound = context.model_copy(update={"phase": phase})
        for plugin in self._plugins:
            if phase not in plugin.triggers:
                continue
            results.append(plugin.run(bound))
        return results
