"""P4 Painter（調色）：大師 LUT + ControlNet 色域。生成前。"""

from __future__ import annotations

from narratron.plugins.context import PluginContext, PluginResult, TriggerPhase


class Painter:
    plugin_id = "P4"
    code = "Painter"
    name_zh = "調色"
    triggers = (TriggerPhase.PRE,)

    def run(self, context: PluginContext) -> PluginResult:
        raise NotImplementedError("Painter 待 Alpha")
