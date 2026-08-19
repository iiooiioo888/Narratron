"""Runner（執行器）：調度 Model Farm + Plugin Bus 生成媒體資產。"""

from __future__ import annotations

from narratron.agents.state import AgentState


class Runner:
    def run(self, state: AgentState) -> AgentState:
        raise NotImplementedError("Runner 生成管線待 Alpha；禁止呼叫模型 API")


def runner_node(state: AgentState) -> AgentState:
    return Runner().run(state)
