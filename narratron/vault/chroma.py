"""向量中樞 Chroma。預設本機索引；可選連 docker-compose 的 chroma 服務。"""

from __future__ import annotations

from typing import Any


class Chroma:
    def __init__(self, url: str | None = None) -> None:
        self._url = url
        self._docs: dict[str, tuple[str, dict[str, Any]]] = {}

    def upsert(self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]]) -> None:
        if not (len(ids) == len(documents) == len(metadatas)):
            raise ValueError("Chroma.upsert 的 ids / documents / metadatas 長度必須一致")
        for doc_id, document, metadata in zip(ids, documents, metadatas, strict=True):
            self._docs[doc_id] = (document, dict(metadata))

    def query(self, text: str, n_results: int = 8) -> list[dict[str, Any]]:
        needle = text.strip().lower()
        scored: list[tuple[int, str, str, dict[str, Any]]] = []
        for doc_id, (document, metadata) in self._docs.items():
            hay = document.lower()
            score = hay.count(needle) if needle else 1
            if needle and needle in hay:
                score += 5
            if score > 0 or not needle:
                scored.append((score, doc_id, document, metadata))
        scored.sort(key=lambda row: (-row[0], row[1]))
        out: list[dict[str, Any]] = []
        for score, doc_id, document, metadata in scored[:n_results]:
            out.append(
                {
                    "id": doc_id,
                    "document": document,
                    "metadata": metadata,
                    "score": score,
                }
            )
        return out
