"""P3 Forker（分岔）：壓抑 / 爆發情緒分支。生成前。"""

from __future__ import annotations

from narratron.plugins.context import PluginContext, PluginResult, TriggerPhase


class Forker:
    plugin_id = "P3"
    code = "Forker"
    name_zh = "分岔"
    triggers = (TriggerPhase.PRE,)

    def run(self, context: PluginContext) -> PluginResult:
        raise NotImplementedError("Forker 待 Alpha")
