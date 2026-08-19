"""P2 Fixer（固形）：鎖死金屬反光率、布料密度。生成前。"""

from __future__ import annotations

from narratron.plugins.context import PluginContext, PluginResult, TriggerPhase


class Fixer:
    plugin_id = "P2"
    code = "Fixer"
    name_zh = "固形"
    triggers = (TriggerPhase.PRE,)

    def run(self, context: PluginContext) -> PluginResult:
        raise NotImplementedError("Fixer 待 Alpha")
