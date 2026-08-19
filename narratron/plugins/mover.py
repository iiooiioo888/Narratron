"""P5 Mover（擬動）：風速、布料、水滴物理。生成前/後。"""

from __future__ import annotations

from narratron.plugins.context import PluginContext, PluginResult, TriggerPhase


class Mover:
    plugin_id = "P5"
    code = "Mover"
    name_zh = "擬動"
    triggers = (TriggerPhase.PRE, TriggerPhase.POST)

    def run(self, context: PluginContext) -> PluginResult:
        raise NotImplementedError("Mover 待 Alpha")
