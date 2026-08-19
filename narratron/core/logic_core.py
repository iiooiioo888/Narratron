"""Logic Core（邏輯內核）：角色決策（Choice）驅動情節，禁止機械降神。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from narratron.agents.state import AgentState


class LogicCore:
    def ensure_choice_driven(self, state: AgentState) -> AgentState:
        raise NotImplementedError("Logic Core 演算法待 Alpha")
