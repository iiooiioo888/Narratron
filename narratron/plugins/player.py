"""P9 Player（配樂）：情緒張力 → 背景音樂與環境音。生成後。

與用戶層 Player（播放器，frontend/player.md）同名不同層。
"""

from __future__ import annotations

from narratron.plugins.context import PluginContext, PluginResult, TriggerPhase


class Player:
    plugin_id = "P9"
    code = "Player"
    name_zh = "配樂"
    triggers = (TriggerPhase.POST,)

    def run(self, context: PluginContext) -> PluginResult:
        raise NotImplementedError("Player 配樂待 Alpha")
