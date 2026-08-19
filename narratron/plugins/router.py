"""P7 Router（路由）：依場景複雜度切換大核/中核。生成前。

本階段唯一允許的非空實作：固定回傳 Mid Core（L1）。
"""

from __future__ import annotations

from narratron.hardware.pools import select_pool
from narratron.plugins.context import PluginContext, PluginResult, TriggerPhase


class Router:
    plugin_id = "P7"
    code = "Router"
    name_zh = "路由"
    triggers = (TriggerPhase.PRE,)

    def run(self, context: PluginContext) -> PluginResult:
        pool = select_pool(context.complexity)
        return PluginResult(
            passed=True,
            metadata={"pool": pool.value, "code": "Mid Core"},
        )
