from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from docmind.domain import Chunk, ScoredChunk, Vector


@runtime_checkable
class VectorStore(Protocol):
    """Tenant-partitioned vector index. Every call is scoped to a single tenant collection."""

    async def upsert(
        self, tenant_id: str, chunks: Sequence[Chunk], embeddings: Sequence[Vector]
    ) -> None: ...

    async def search(
        self,
        tenant_id: str,
        query: Vector,
        k: int,
        *,
        document_ids: Sequence[str] | None = None,
    ) -> list[ScoredChunk]:
        """Top-``k`` chunks by cosine similarity. Results carry embeddings (needed for MMR)."""
        ...

    async def delete_document(self, tenant_id: str, document_id: str) -> int: ...

    async def count(self, tenant_id: str) -> int: ...

    async def close(self) -> None: ...
