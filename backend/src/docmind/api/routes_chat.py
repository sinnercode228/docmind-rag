from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from docmind.api.deps import ContainerDep, SessionDep, TenantDep
from docmind.api.schemas import (
    ChatRequest,
    ChatResponse,
    CitationOut,
    ConversationOut,
    MessageOut,
    SearchRequest,
    SearchResponse,
)
from docmind.container import Container
from docmind.db import repositories as repo
from docmind.errors import DocMindError
from docmind.rag.service import DeltaEvent, DoneEvent, SourcesEvent

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["chat"])


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _chat_events(
    container: Container, tenant_id: str, body: ChatRequest
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """The chat use-case as a sequence of (event, payload) pairs; shared by JSON and SSE."""
    async with container.sessions() as session:
        conversation = await repo.get_or_create_conversation(
            session, tenant_id, body.conversation_id, title=body.question.strip()[:80]
        )
        history = await repo.conversation_history(
            session, conversation.id, container.settings.history_turns
        )
        user_message = await repo.add_message(session, conversation, "user", body.question)
        await session.commit()
    yield "meta", {"conversation_id": conversation.id, "user_message_id": user_message.id}

    citations: list[dict[str, Any]] = []
    async for event in container.rag.stream_answer(
        tenant_id,
        body.question,
        history=history,
        top_k=body.top_k,
        document_ids=body.document_ids,
    ):
        if isinstance(event, SourcesEvent):
            citations = [c.to_dict() for c in event.citations]
            yield "sources", {"citations": citations}
        elif isinstance(event, DeltaEvent):
            yield "delta", {"text": event.text}
        elif isinstance(event, DoneEvent):
            async with container.sessions() as session:
                conversation = await repo.get_or_create_conversation(
                    session, tenant_id, conversation.id, title=""
                )
                for citation in citations:
                    citation["cited"] = citation["index"] in event.cited
                assistant = await repo.add_message(
                    session, conversation, "assistant", event.answer, citations
                )
                await session.commit()
            yield (
                "done",
                {
                    "message_id": assistant.id,
                    "answer": event.answer,
                    "cited": event.cited,
                    "model": event.model,
                    "stop_reason": event.stop_reason,
                    "usage": {
                        "input_tokens": event.input_tokens,
                        "output_tokens": event.output_tokens,
                    },
                },
            )


@router.post("/chat", response_model=ChatResponse, summary="Ask a question (single JSON reply)")
async def chat(body: ChatRequest, tenant: TenantDep, container: ContainerDep) -> ChatResponse:
    meta: dict[str, Any] = {}
    citations: list[dict[str, Any]] = []
    done: dict[str, Any] = {}
    async for name, payload in _chat_events(container, tenant.id, body):
        if name == "meta":
            meta = payload
        elif name == "sources":
            citations = payload["citations"]
        elif name == "done":
            done = payload
    return ChatResponse(
        conversation_id=meta["conversation_id"],
        message_id=done["message_id"],
        answer=done["answer"],
        citations=[CitationOut.model_validate(c) for c in citations],
        cited=done["cited"],
        model=done["model"],
        stop_reason=done["stop_reason"],
    )


@router.post(
    "/chat/stream",
    summary="Ask a question and stream the answer as Server-Sent Events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def chat_stream(
    body: ChatRequest, tenant: TenantDep, container: ContainerDep
) -> StreamingResponse:
    if body.conversation_id:  # fail fast with a proper 404 before the stream starts
        async with container.sessions() as session:
            await repo.get_or_create_conversation(
                session, tenant.id, body.conversation_id, title=""
            )

    async def generate() -> AsyncIterator[str]:
        try:
            async for name, payload in _chat_events(container, tenant.id, body):
                yield sse(name, payload)
        except DocMindError as exc:
            yield sse("error", {"error": exc.code, "message": exc.message})
        except Exception:
            log.exception("chat stream failed")
            yield sse("error", {"error": "internal_error", "message": "Unexpected server error"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/search", response_model=SearchResponse, summary="Retrieval only (no LLM)")
async def search(body: SearchRequest, tenant: TenantDep, container: ContainerDep) -> SearchResponse:
    citations = await container.rag.search(
        tenant.id, body.query, top_k=body.top_k, document_ids=body.document_ids
    )
    return SearchResponse(results=[CitationOut.model_validate(c.to_dict()) for c in citations])


@router.get("/conversations", response_model=list[ConversationOut], tags=["conversations"])
async def list_conversations(tenant: TenantDep, session: SessionDep) -> list[ConversationOut]:
    rows = await repo.list_conversations(session, tenant.id)
    return [ConversationOut.model_validate(c) for c in rows]


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageOut],
    tags=["conversations"],
)
async def conversation_messages(
    conversation_id: str, tenant: TenantDep, session: SessionDep
) -> list[MessageOut]:
    rows = await repo.conversation_messages(session, tenant.id, conversation_id)
    return [MessageOut.model_validate(m) for m in rows]


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["conversations"],
)
async def delete_conversation(conversation_id: str, tenant: TenantDep, session: SessionDep) -> None:
    await repo.delete_conversation(session, tenant.id, conversation_id)
    await session.commit()
