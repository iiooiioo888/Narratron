"""Causal Link（因果橋）：Trace Log → 動態視覺形容詞。"""

from __future__ import annotations

from narratron.vault.schema import TraceRecord


class CausalLink:
    def translate(self, traces: list[TraceRecord]) -> str:
        raise NotImplementedError("Causal Link 演算法待 Alpha Q2")
