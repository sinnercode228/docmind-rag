"""PostgreSQL + pgvector store: HNSW cosine index, tenant-partitioned rows."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from sqlalchemy import Column, Index, Integer, MetaData, String, Table, Text, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from docmind.domain import Chunk, ScoredChunk, Vector


def build_table(dim: int) -> Table:
    from pgvector.sqlalchemy import Vector as PgVector

    metadata = MetaData()
    table = Table(
        "chunk_vectors",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("tenant_id", String(64), nullable=False),
        Column("document_id", String(64), nullable=False),
        Column("ordinal", Integer, nullable=False),
        Column("text", Text, nullable=False),
        Column("page", Integer),
        Column("heading", Text),
        Column("start", Integer, nullable=False, default=0),
        Column("end", Integer, nullable=False, default=0),
        Column("embedding", PgVector(dim), nullable=False),
    )
    Index("ix_chunk_vectors_tenant_doc", table.c.tenant_id, table.c.document_id)
    Index(
        "ix_chunk_vectors_embedding_hnsw",
        table.c.embedding,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    return table


class PgVectorStore:
    def __init__(self, engine: AsyncEngine, dim: int) -> None:
        self._engine = engine
        self._dim = dim
        self._table = build_table(dim)

    @classmethod
    def from_url(cls, url: str, dim: int) -> PgVectorStore:
        return cls(create_async_engine(url, pool_pre_ping=True), dim)

    async def init(self) -> None:
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(self._table.metadata.create_all)

    @staticmethod
    def _row_to_chunk(row: Any) -> Chunk:
        return Chunk(
            id=row.id,
            document_id=row.document_id,
            ordinal=row.ordinal,
            text=row.text,
            page=row.page,
            heading=row.heading,
            start=row.start,
            end=row.end,
        )

    async def upsert(
        self, tenant_id: str, chunks: Sequence[Chunk], embeddings: Sequence[Vector]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        if not chunks:
            return
        rows = [
            {
                "id": c.id,
                "tenant_id": tenant_id,
                "document_id": c.document_id,
                "ordinal": c.ordinal,
                "text": c.text,
                "page": c.page,
                "heading": c.heading,
                "start": c.start,
                "end": c.end,
                "embedding": np.asarray(e, dtype=np.float32),
            }
            for c, e in zip(chunks, embeddings, strict=True)
        ]
        statement = insert(self._table)
        statement = statement.on_conflict_do_update(
            index_elements=[self._table.c.id],
            set_={
                col: statement.excluded[col]
                for col in ("text", "page", "heading", "start", "end", "embedding")
            },
        )
        async with self._engine.begin() as conn:
            await conn.execute(statement, rows)

    async def search(
        self,
        tenant_id: str,
        query: Vector,
        k: int,
        *,
        document_ids: Sequence[str] | None = None,
    ) -> list[ScoredChunk]:
        t = self._table
        distance = t.c.embedding.cosine_distance(np.asarray(query, dtype=np.float32))
        statement = (
            select(t, distance.label("distance"))
            .where(t.c.tenant_id == tenant_id)
            .order_by(distance)
            .limit(k)
        )
        if document_ids is not None:
            statement = statement.where(t.c.document_id.in_(list(document_ids)))
        async with self._engine.connect() as conn:
            rows = (await conn.execute(statement)).all()
        return [
            ScoredChunk(
                self._row_to_chunk(row),
                1.0 - float(row.distance),
                np.asarray(row.embedding, dtype=np.float32),
            )
            for row in rows
        ]

    async def delete_document(self, tenant_id: str, document_id: str) -> int:
        t = self._table
        async with self._engine.begin() as conn:
            result = await conn.execute(
                delete(t).where(t.c.tenant_id == tenant_id, t.c.document_id == document_id)
            )
        return int(result.rowcount or 0)

    async def count(self, tenant_id: str) -> int:
        t = self._table
        async with self._engine.connect() as conn:
            value = await conn.scalar(select(func.count()).where(t.c.tenant_id == tenant_id))
        return int(value or 0)

    async def close(self) -> None:
        await self._engine.dispose()
