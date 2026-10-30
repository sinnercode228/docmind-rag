"""Behaviour of RAGService.stream_answer around retrieval and conversation history."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import numpy as np

from docmind.domain import ChatTurn, Chunk, ScoredChunk
from docmind.llm.base import Completion, LLMRequest, TextDelta
from docmind.rag.service import RAGService, SourcesEvent


class RecordingRetriever:
    """Captures the query string the service actually retrieves on."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def retrieve(
        self,
        tenant_id: str,
        query: str,
        *,
        top_k: int | None = None,
        document_ids: Sequence[str] | None = None,
    ) -> list[ScoredChunk]:
        self.queries.append(query)
        chunk = Chunk(
            id="d:1", document_id="d", ordinal=0, text="The Nimbus plan costs $9 a month."
        )
        return [ScoredChunk(chunk, 0.9, np.ones(4, dtype=np.float32))]


class StubLLM:
    name = "stub"

    async def stream(self, request: LLMRequest) -> AsyncIterator[TextDelta | Completion]:
        yield TextDelta("It costs $9 a month [1].")
        yield Completion(stop_reason="end_turn", model=self.name)

    async def aclose(self) -> None:
        return None


async def _titles(tenant_id: str, document_ids: Sequence[str]) -> dict[str, str]:
    return dict.fromkeys(document_ids, "Nimbus plan")


def _service(retriever: RecordingRetriever) -> RAGService:
    return RAGService(retriever, StubLLM(), _titles)  # type: ignore[arg-type]


async def test_followup_retrieval_includes_the_conversation() -> None:
    retriever = RecordingRetriever()
    history = [
        ChatTurn(role="user", content="Tell me about the Nimbus plan"),
        ChatTurn(role="assistant", content="The Nimbus plan is our mid tier."),
    ]
    events = [
        event
        async for event in _service(retriever).stream_answer(
            "t", "what does it cost?", history=history
        )
    ]

    assert any(isinstance(event, SourcesEvent) for event in events)
    assert retriever.queries, "retriever was never called"
    query = retriever.queries[0]
    assert "what does it cost?" in query
    # "it" only means something because the subject is in the history.
    assert "Nimbus" in query


async def test_retrieval_query_is_the_bare_question_without_history() -> None:
    retriever = RecordingRetriever()
    _ = [event async for event in _service(retriever).stream_answer("t", "what does it cost?")]
    assert retriever.queries == ["what does it cost?"]
