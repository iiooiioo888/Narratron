"""Muxer（合流器）：後期合成（拼接、轉場、字幕）；綁定 Light Core + FFmpeg。"""

from __future__ import annotations

from narratron.agents.state import AgentState


class Muxer:
    def mux(self, state: AgentState) -> AgentState:
        raise NotImplementedError("Muxer 後期合成待 Alpha Q4")


def muxer_node(state: AgentState) -> AgentState:
    return Muxer().mux(state)
