"""P12 Exporter（轉檔）：.draft（剪映）與 .xml（PR）。生成後。"""

from __future__ import annotations

from narratron.plugins.context import PluginContext, PluginResult, TriggerPhase


class Exporter:
    plugin_id = "P12"
    code = "Exporter"
    name_zh = "轉檔"
    triggers = (TriggerPhase.POST,)

    def run(self, context: PluginContext) -> PluginResult:
        raise NotImplementedError("Exporter 待 Alpha Q4")
