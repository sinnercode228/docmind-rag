"""Structure-aware recursive text splitter that keeps character offsets for citations.

The splitter first cuts text on the "strongest" boundary available (paragraphs, then lines,
then sentences, then words) until every piece fits ``chunk_size``; it then greedily packs
pieces back together and carries ``chunk_overlap`` characters of context between chunks.
Offsets always point into the original section text, so the UI can highlight the exact span.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from docmind.domain import Chunk, ExtractedDocument

SEPARATORS: tuple[str, ...] = ("\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ")


@dataclass(slots=True, frozen=True)
class Span:
    start: int
    end: int


def _split(text: str, start: int, end: int, size: int, seps: tuple[str, ...]) -> list[Span]:
    if end - start <= size:
        return [Span(start, end)]
    if not seps:  # no boundary left: hard cut
        return [Span(i, min(i + size, end)) for i in range(start, end, size)]
    sep, rest = seps[0], seps[1:]
    pieces: list[Span] = []
    cursor = start
    while cursor < end:
        idx = text.find(sep, cursor, end)
        stop = end if idx == -1 else idx + len(sep)
        pieces.append(Span(cursor, stop))
        cursor = stop
    if len(pieces) == 1:
        return _split(text, start, end, size, rest)
    out: list[Span] = []
    for piece in pieces:
        out.extend(_split(text, piece.start, piece.end, size, rest))
    return out


def split_text(text: str, chunk_size: int = 900, chunk_overlap: int = 150) -> list[Span]:
    """Return ``[start, end)`` spans covering ``text`` in chunks of at most ``chunk_size``."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not 0 <= chunk_overlap < chunk_size:
        raise ValueError("chunk_overlap must be in [0, chunk_size)")
    pieces = _split(text, 0, len(text), chunk_size, SEPARATORS)
    spans: list[Span] = []
    i = 0
    while i < len(pieces):
        start = pieces[i].start
        end = pieces[i].end
        j = i + 1
        while j < len(pieces) and pieces[j].end - start <= chunk_size:
            end = pieces[j].end
            j += 1
        spans.append(Span(start, end))
        if j >= len(pieces):
            break
        # step back over trailing pieces to create overlap, but always make progress
        # (and only while the next piece still fits next to the carried-over context)
        k = j
        while (
            k - 1 > i
            and end - pieces[k - 1].start <= chunk_overlap
            and pieces[j].end - pieces[k - 1].start <= chunk_size
        ):
            k -= 1
        i = k
    return [_strip(text, s) for s in spans if text[s.start : s.end].strip()]


def _strip(text: str, span: Span) -> Span:
    start, end = span.start, span.end
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return Span(start, end)


def chunk_id(document_id: str, ordinal: int, text: str) -> str:
    digest = hashlib.blake2b(f"{document_id}:{ordinal}:{text}".encode(), digest_size=8)
    return f"ch_{digest.hexdigest()}"


def chunk_document(
    document: ExtractedDocument,
    document_id: str,
    *,
    chunk_size: int = 900,
    chunk_overlap: int = 150,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in document.sections:
        for span in split_text(section.text, chunk_size, chunk_overlap):
            body = section.text[span.start : span.end]
            ordinal = len(chunks)
            chunks.append(
                Chunk(
                    id=chunk_id(document_id, ordinal, body),
                    document_id=document_id,
                    ordinal=ordinal,
                    text=body,
                    page=section.page,
                    heading=section.heading,
                    start=span.start,
                    end=span.end,
                )
            )
    return chunks
