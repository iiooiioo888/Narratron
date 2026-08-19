"""P8 Recycler（重生）：舊圖條件遷移。生成前。"""

from __future__ import annotations

from narratron.plugins.context import PluginContext, PluginResult, TriggerPhase


class Recycler:
    plugin_id = "P8"
    code = "Recycler"
    name_zh = "重生"
    triggers = (TriggerPhase.PRE,)

    def run(self, context: PluginContext) -> PluginResult:
        raise NotImplementedError("Recycler 待 Alpha Q3")
