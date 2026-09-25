"""Retrieval-augmented answering as a stream of typed events (sources -> deltas -> done)."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from docmind.domain import ChatTurn, Citation, ScoredChunk
from docmind.llm.base import Completion, LLMProvider, SourceBlock, TextDelta
from docmind.rag.prompt import build_request, format_location
from docmind.retrieval.retriever import Retriever
from docmind.text import best_sentence

TitleLookup = Callable[[str, Sequence[str]], Awaitable[dict[str, str]]]
_CITE = re.compile(r"\[(\d{1,2})\]")


@dataclass(slots=True, frozen=True)
class SourcesEvent:
    citations: list[Citation]


@dataclass(slots=True, frozen=True)
class DeltaEvent:
    text: str


@dataclass(slots=True, frozen=True)
class DoneEvent:
    answer: str
    stop_reason: str
    model: str
    cited: list[int] = field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None


RagEvent = SourcesEvent | DeltaEvent | DoneEvent


def cited_indices(answer: str, available: int) -> list[int]:
    found = {int(m) for m in _CITE.findall(answer)}
    return sorted(i for i in found if 1 <= i <= available)


def to_citations(question: str, hits: list[ScoredChunk], titles: dict[str, str]) -> list[Citation]:
    citations = []
    for index, hit in enumerate(hits, start=1):
        chunk = hit.chunk
        citations.append(
            Citation(
                index=index,
                document_id=chunk.document_id,
                document_title=titles.get(chunk.document_id, "Untitled"),
                chunk_id=chunk.id,
                snippet=chunk.text,
                score=hit.score,
                page=chunk.page,
                heading=chunk.heading,
                highlight=best_sentence(chunk.text, question),
            )
        )
    return citations


class RAGService:
    def __init__(
        self,
        retriever: Retriever,
        llm: LLMProvider,
        titles: TitleLookup,
        *,
        max_tokens: int = 4096,
        history_turns: int = 4,
    ) -> None:
        self._retriever = retriever
        self._llm = llm
        self._titles = titles
        self._max_tokens = max_tokens
        self._history_turns = history_turns

    @property
    def llm_name(self) -> str:
        return self._llm.name

    async def search(
        self,
        tenant_id: str,
        query: str,
        *,
        top_k: int | None = None,
        document_ids: Sequence[str] | None = None,
    ) -> list[Citation]:
        hits = await self._retriever.retrieve(
            tenant_id, query, top_k=top_k, document_ids=document_ids
        )
        titles = await self._titles(tenant_id, sorted({h.chunk.document_id for h in hits}))
        return to_citations(query, hits, titles)

    async def stream_answer(
        self,
        tenant_id: str,
        question: str,
        *,
        history: Sequence[ChatTurn] = (),
        top_k: int | None = None,
        document_ids: Sequence[str] | None = None,
    ) -> AsyncIterator[RagEvent]:
        citations = await self.search(tenant_id, question, top_k=top_k, document_ids=document_ids)
        yield SourcesEvent(citations)

        sources = [
            SourceBlock(
                index=c.index,
                title=c.document_title,
                text=c.snippet,
                location=format_location(c.page, c.heading),
            )
            for c in citations
        ]
        recent = list(history)[-self._history_turns * 2 :] if self._history_turns else []
        request = build_request(question, sources, recent, max_tokens=self._max_tokens)

        parts: list[str] = []
        completion = Completion(stop_reason="end_turn", model=self._llm.name)
        async for event in self._llm.stream(request):
            if isinstance(event, TextDelta):
                parts.append(event.text)
                yield DeltaEvent(event.text)
            else:
                completion = event
        answer = "".join(parts)
        yield DoneEvent(
            answer=answer,
            stop_reason=completion.stop_reason,
            model=completion.model,
            cited=cited_indices(answer, len(citations)),
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
        )
