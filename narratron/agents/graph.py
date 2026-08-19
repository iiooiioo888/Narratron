"""LangGraph 編排：Parser → Director → Keeper → Runner → Muxer。"""

from __future__ import annotations

from typing import Any

from narratron.agents.director import director_node
from narratron.agents.keeper import keeper_node
from narratron.agents.muxer import muxer_node
from narratron.agents.parser import parser_node
from narratron.agents.runner import runner_node
from narratron.agents.state import AgentState

NODE_ORDER: tuple[str, ...] = ("Parser", "Director", "Keeper", "Runner", "Muxer")


def build_graph() -> Any:
    """編譯可 import 的圖。Parser / Director 已通；Keeper 起仍為 stub。"""

    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(AgentState)
    graph.add_node("Parser", parser_node)
    graph.add_node("Director", director_node)
    graph.add_node("Keeper", keeper_node)
    graph.add_node("Runner", runner_node)
    graph.add_node("Muxer", muxer_node)
    graph.add_edge(START, "Parser")
    graph.add_edge("Parser", "Director")
    graph.add_edge("Director", "Keeper")
    graph.add_edge("Keeper", "Runner")
    graph.add_edge("Runner", "Muxer")
    graph.add_edge("Muxer", END)
    return graph.compile()
