"""P11 Cropper（裁切）：16:9 母版 → 9:16 / 1:1。生成後。"""

from __future__ import annotations

from narratron.plugins.context import PluginContext, PluginResult, TriggerPhase


class Cropper:
    plugin_id = "P11"
    code = "Cropper"
    name_zh = "裁切"
    triggers = (TriggerPhase.POST,)

    def run(self, context: PluginContext) -> PluginResult:
        raise NotImplementedError("Cropper 待 Alpha")
