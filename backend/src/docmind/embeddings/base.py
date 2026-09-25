from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from docmind.domain import Vector


@runtime_checkable
class Embedder(Protocol):
    """Turns text into L2-normalised float32 vectors of a fixed dimension."""

    @property
    def dim(self) -> int: ...

    @property
    def name(self) -> str: ...

    async def embed_documents(self, texts: list[str]) -> list[Vector]: ...

    async def embed_query(self, text: str) -> Vector: ...


def l2_normalize(vector: Vector) -> Vector:
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        return vector
    return (vector / norm).astype(np.float32)
