"""P6 Screener（篩檢）：CV 連續性比對。生成後。核心護城河。"""

from __future__ import annotations

from narratron.plugins.context import PluginContext, PluginResult, TriggerPhase


class Screener:
    plugin_id = "P6"
    code = "Screener"
    name_zh = "篩檢"
    triggers = (TriggerPhase.POST,)

    def run(self, context: PluginContext) -> PluginResult:
        raise NotImplementedError("Screener CV 待 Alpha Q2")
