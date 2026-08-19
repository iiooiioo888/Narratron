"""Compressor（壓縮器）：多時間點前因 → 一句高密度物理/心理描述。"""

from __future__ import annotations


class Compressor:
    def compress(self, antecedents: list[str]) -> str:
        raise NotImplementedError("Compressor 演算法待 Alpha Q2")
