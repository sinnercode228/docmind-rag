"""Core domain types shared across ingestion, retrieval and generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import numpy.typing as npt

Vector = npt.NDArray[np.float32]
Role = Literal["user", "assistant"]


@dataclass(slots=True, frozen=True)
class Section:
    """A contiguous piece of extracted text with its location in the source (page, heading)."""

    text: str
    page: int | None = None
    heading: str | None = None


@dataclass(slots=True, frozen=True)
class ExtractedDocument:
    title: str
    sections: list[Section]
    mime_type: str


@dataclass(slots=True, frozen=True)
class Chunk:
    """A retrievable unit of text. ``start``/``end`` are char offsets within its section."""

    id: str
    document_id: str
    ordinal: int
    text: str
    page: int | None = None
    heading: str | None = None
    start: int = 0
    end: int = 0

    def metadata(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "heading": self.heading,
            "start": self.start,
            "end": self.end,
        }


@dataclass(slots=True, frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float
    embedding: Vector | None = field(default=None, compare=False, repr=False)


@dataclass(slots=True, frozen=True)
class Citation:
    """A numbered source attached to an answer. ``highlight`` is a [start, end) span in snippet."""

    index: int
    document_id: str
    document_title: str
    chunk_id: str
    snippet: str
    score: float
    page: int | None = None
    heading: str | None = None
    highlight: tuple[int, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "document_id": self.document_id,
            "document_title": self.document_title,
            "chunk_id": self.chunk_id,
            "snippet": self.snippet,
            "score": round(self.score, 4),
            "page": self.page,
            "heading": self.heading,
            "highlight": list(self.highlight) if self.highlight else None,
        }


@dataclass(slots=True, frozen=True)
class ChatTurn:
    role: Role
    content: str
