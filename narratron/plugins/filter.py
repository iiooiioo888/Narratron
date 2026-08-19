"""P10 Filter（濾聲）：聽覺 POV。生成後。"""

from __future__ import annotations

from narratron.plugins.context import PluginContext, PluginResult, TriggerPhase


class Filter:
    plugin_id = "P10"
    code = "Filter"
    name_zh = "濾聲"
    triggers = (TriggerPhase.POST,)

    def run(self, context: PluginContext) -> PluginResult:
        raise NotImplementedError("Filter 待 Alpha")
