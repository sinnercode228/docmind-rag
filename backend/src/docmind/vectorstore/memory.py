"""NumPy-backed in-memory vector store with optional on-disk snapshots (dev/test/demo)."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from docmind.domain import Chunk, ScoredChunk, Vector

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


@dataclass
class _Collection:
    dim: int
    chunks: list[Chunk] = field(default_factory=list)
    matrix: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.matrix = np.zeros((0, self.dim), dtype=np.float32)


class MemoryVectorStore:
    def __init__(self, dim: int, persist_dir: str | Path | None = None) -> None:
        self._dim = dim
        self._collections: dict[str, _Collection] = {}
        self._lock = asyncio.Lock()
        self._persist_dir = Path(persist_dir) if persist_dir else None
        if self._persist_dir:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            self._load_all()

    # -- persistence ---------------------------------------------------------------------------
    def _paths(self, tenant_id: str) -> tuple[Path, Path]:
        assert self._persist_dir is not None
        stem = _SAFE.sub("_", tenant_id)
        return self._persist_dir / f"{stem}.json", self._persist_dir / f"{stem}.npy"

    def _save(self, tenant_id: str) -> None:
        if not self._persist_dir:
            return
        meta_path, matrix_path = self._paths(tenant_id)
        collection = self._collections[tenant_id]
        meta = {"tenant_id": tenant_id, "chunks": [asdict(c) for c in collection.chunks]}
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        np.save(matrix_path, collection.matrix)

    def _load_all(self) -> None:
        assert self._persist_dir is not None
        for meta_path in self._persist_dir.glob("*.json"):
            matrix_path = meta_path.with_suffix(".npy")
            if not matrix_path.exists():
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            matrix = np.load(matrix_path)
            if matrix.ndim != 2 or matrix.shape[1] != self._dim:
                continue  # stale snapshot from a different embedder; ignore
            collection = _Collection(self._dim, [Chunk(**c) for c in meta["chunks"]])
            collection.matrix = matrix.astype(np.float32)
            self._collections[meta["tenant_id"]] = collection

    # -- VectorStore API -----------------------------------------------------------------------
    def _collection(self, tenant_id: str) -> _Collection:
        return self._collections.setdefault(tenant_id, _Collection(self._dim))

    async def upsert(
        self, tenant_id: str, chunks: Sequence[Chunk], embeddings: Sequence[Vector]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        if not chunks:
            return
        new = np.vstack([np.asarray(e, dtype=np.float32) for e in embeddings])
        if new.shape[1] != self._dim:
            raise ValueError(f"expected dim {self._dim}, got {new.shape[1]}")
        async with self._lock:
            collection = self._collection(tenant_id)
            incoming = {c.id for c in chunks}
            keep = [i for i, c in enumerate(collection.chunks) if c.id not in incoming]
            collection.chunks = [collection.chunks[i] for i in keep] + list(chunks)
            collection.matrix = np.vstack([collection.matrix[keep], new])
            self._save(tenant_id)

    async def search(
        self,
        tenant_id: str,
        query: Vector,
        k: int,
        *,
        document_ids: Sequence[str] | None = None,
    ) -> list[ScoredChunk]:
        collection = self._collections.get(tenant_id)
        if collection is None or not collection.chunks or k <= 0:
            return []
        scores = collection.matrix @ np.asarray(query, dtype=np.float32)
        if document_ids is not None:
            allowed = set(document_ids)
            mask = np.array([c.document_id in allowed for c in collection.chunks])
            scores = np.where(mask, scores, -np.inf)
        k = min(k, len(collection.chunks))
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [
            ScoredChunk(collection.chunks[i], float(scores[i]), collection.matrix[i])
            for i in top
            if np.isfinite(scores[i])
        ]

    async def delete_document(self, tenant_id: str, document_id: str) -> int:
        async with self._lock:
            collection = self._collections.get(tenant_id)
            if collection is None:
                return 0
            keep = [i for i, c in enumerate(collection.chunks) if c.document_id != document_id]
            removed = len(collection.chunks) - len(keep)
            collection.chunks = [collection.chunks[i] for i in keep]
            collection.matrix = collection.matrix[keep]
            self._save(tenant_id)
            return removed

    async def count(self, tenant_id: str) -> int:
        collection = self._collections.get(tenant_id)
        return len(collection.chunks) if collection else 0

    async def close(self) -> None:
        return None
