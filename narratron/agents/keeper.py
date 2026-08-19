"""Keeper（守護器）：守護視覺連續性；呼叫 Tracer / Screener 介面。"""

from __future__ import annotations

from narratron.agents.state import AgentState


class Keeper:
    def keep(self, state: AgentState) -> AgentState:
        raise NotImplementedError("Keeper 因果不斷檔待 Alpha Q2")


def keeper_node(state: AgentState) -> AgentState:
    return Keeper().keep(state)
