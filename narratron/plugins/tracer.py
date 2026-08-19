"""P1 Tracer（追跡）：創傷年表 → Prompt 肢體顫抖、退縮反應。生成前。"""

from __future__ import annotations

from narratron.plugins.context import PluginContext, PluginResult, TriggerPhase


class Tracer:
    plugin_id = "P1"
    code = "Tracer"
    name_zh = "追跡"
    triggers = (TriggerPhase.PRE,)

    def run(self, context: PluginContext) -> PluginResult:
        raise NotImplementedError("Tracer 待 Alpha")
