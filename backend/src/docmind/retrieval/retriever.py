from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from docmind.domain import ScoredChunk
from docmind.embeddings.base import Embedder
from docmind.retrieval.mmr import mmr_select
from docmind.vectorstore.base import VectorStore


@dataclass(slots=True)
class RetrievalParams:
    top_k: int = 5
    fetch_k: int = 24
    mmr_lambda: float = 0.6
    min_score: float = 0.05


class Retriever:
    """Dense retrieval (fetch_k nearest) followed by MMR re-ranking down to top_k."""

    def __init__(self, embedder: Embedder, store: VectorStore, params: RetrievalParams) -> None:
        self._embedder = embedder
        self._store = store
        self.params = params

    async def retrieve(
        self,
        tenant_id: str,
        query: str,
        *,
        top_k: int | None = None,
        document_ids: Sequence[str] | None = None,
    ) -> list[ScoredChunk]:
        k = top_k or self.params.top_k
        vector = await self._embedder.embed_query(query)
        candidates = await self._store.search(
            tenant_id, vector, max(self.params.fetch_k, k), document_ids=document_ids
        )
        seen: set[str] = set()
        unique: list[ScoredChunk] = []
        for candidate in candidates:
            key = candidate.chunk.text.strip().lower()
            if candidate.score < self.params.min_score or key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return mmr_select(unique, k, self.params.mmr_lambda)
