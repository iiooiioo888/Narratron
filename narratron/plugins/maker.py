"""P13 Maker（製本）：圖文分鏡腳本 PDF。生成後。"""

from __future__ import annotations

from narratron.plugins.context import PluginContext, PluginResult, TriggerPhase


class Maker:
    plugin_id = "P13"
    code = "Maker"
    name_zh = "製本"
    triggers = (TriggerPhase.POST,)

    def run(self, context: PluginContext) -> PluginResult:
        raise NotImplementedError("Maker 待 Alpha")
