"""Data-access helpers. Every query touching tenant data is filtered by ``tenant_id``."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from docmind.db.models import (
    ApiKey,
    Conversation,
    Document,
    DocumentBlob,
    Job,
    Message,
    Tenant,
    utcnow,
)
from docmind.domain import ChatTurn
from docmind.errors import NotFoundError

KEY_PREFIX = "dm_"


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


# -- tenants & keys ------------------------------------------------------------------------------


async def create_tenant(
    session: AsyncSession, name: str, *, raw_key: str | None = None, label: str | None = None
) -> tuple[Tenant, str]:
    tenant = Tenant(name=name)
    session.add(tenant)
    await session.flush()
    raw = raw_key or generate_api_key()
    session.add(ApiKey(tenant_id=tenant.id, key_hash=hash_key(raw), prefix=raw[:10], label=label))
    await session.flush()
    return tenant, raw


async def tenant_for_key(session: AsyncSession, raw_key: str) -> Tenant | None:
    row = await session.scalar(
        select(ApiKey).where(ApiKey.key_hash == hash_key(raw_key), ApiKey.revoked_at.is_(None))
    )
    return row.tenant if row else None


async def ensure_bootstrap_tenant(session: AsyncSession, raw_key: str) -> Tenant:
    existing = await tenant_for_key(session, raw_key)
    if existing:
        return existing
    tenant, _ = await create_tenant(session, "default", raw_key=raw_key, label="bootstrap")
    return tenant


# -- documents -----------------------------------------------------------------------------------


async def add_document(
    session: AsyncSession,
    *,
    tenant_id: str,
    title: str,
    source_type: str,
    source: str,
    mime_type: str | None,
    data: bytes | None,
) -> tuple[Document, Job]:
    document = Document(
        tenant_id=tenant_id,
        title=title[:500],
        source_type=source_type,
        source=source,
        mime_type=mime_type,
        size_bytes=len(data) if data else 0,
        content_hash=hashlib.sha256(data).hexdigest() if data else None,
        status="queued",
    )
    session.add(document)
    await session.flush()
    if data is not None:
        session.add(DocumentBlob(document_id=document.id, data=data))
    job = Job(tenant_id=tenant_id, document_id=document.id)
    session.add(job)
    await session.flush()
    return document, job


async def get_document(session: AsyncSession, tenant_id: str, document_id: str) -> Document:
    document = await session.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    if document is None:
        raise NotFoundError(f"Document {document_id} not found")
    return document


async def list_documents(session: AsyncSession, tenant_id: str) -> Sequence[Document]:
    result = await session.scalars(
        select(Document).where(Document.tenant_id == tenant_id).order_by(Document.created_at.desc())
    )
    return result.all()


async def document_titles(
    session: AsyncSession, tenant_id: str, ids: Sequence[str]
) -> dict[str, str]:
    if not ids:
        return {}
    rows = await session.execute(
        select(Document.id, Document.title).where(
            Document.tenant_id == tenant_id, Document.id.in_(list(ids))
        )
    )
    return {row.id: row.title for row in rows}


async def get_blob(session: AsyncSession, document_id: str) -> bytes | None:
    blob = await session.get(DocumentBlob, document_id)
    return blob.data if blob else None


async def save_blob(session: AsyncSession, document_id: str, data: bytes) -> None:
    await session.merge(DocumentBlob(document_id=document_id, data=data))


async def delete_document(session: AsyncSession, tenant_id: str, document_id: str) -> None:
    document = await get_document(session, tenant_id, document_id)
    await session.execute(delete(Job).where(Job.document_id == document.id))
    await session.execute(delete(DocumentBlob).where(DocumentBlob.document_id == document.id))
    await session.delete(document)


async def tenant_stats(session: AsyncSession, tenant_id: str) -> dict[str, int]:
    docs = await session.scalar(
        select(func.count()).select_from(Document).where(Document.tenant_id == tenant_id)
    )
    chunks = await session.scalar(
        select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
            Document.tenant_id == tenant_id
        )
    )
    return {"documents": int(docs or 0), "chunks": int(chunks or 0)}


# -- jobs ----------------------------------------------------------------------------------------


async def get_job(session: AsyncSession, tenant_id: str, job_id: str) -> Job:
    job = await session.scalar(select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id))
    if job is None:
        raise NotFoundError(f"Job {job_id} not found")
    return job


async def create_job(session: AsyncSession, document: Document) -> Job:
    job = Job(tenant_id=document.tenant_id, document_id=document.id)
    document.status = "queued"
    document.error = None
    session.add(job)
    await session.flush()
    return job


async def pending_job_ids(session: AsyncSession) -> list[str]:
    """Jobs left queued/running by a previous process (crash or restart) - to be re-queued."""
    rows = await session.scalars(
        select(Job.id).where(Job.status.in_(["queued", "running"])).order_by(Job.created_at)
    )
    return list(rows.all())


async def mark_job(
    session: AsyncSession,
    job_id: str,
    status: str,
    *,
    error: str | None = None,
    started: datetime | None = None,
) -> None:
    values: dict[str, object] = {"status": status, "error": error}
    if status == "running":
        values["started_at"] = started or utcnow()
        values["attempts"] = Job.attempts + 1
    if status in {"succeeded", "failed"}:
        values["finished_at"] = utcnow()
    await session.execute(update(Job).where(Job.id == job_id).values(**values))


# -- conversations -------------------------------------------------------------------------------


async def get_or_create_conversation(
    session: AsyncSession,
    tenant_id: str,
    conversation_id: str | None,
    *,
    title: str,
    channel: str = "web",
) -> Conversation:
    if conversation_id:
        conversation = await session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.tenant_id == tenant_id
            )
        )
        if conversation is None:
            raise NotFoundError(f"Conversation {conversation_id} not found")
        return conversation
    conversation = Conversation(tenant_id=tenant_id, title=title[:300], channel=channel)
    session.add(conversation)
    await session.flush()
    return conversation


async def list_conversations(
    session: AsyncSession, tenant_id: str, limit: int = 50
) -> Sequence[Conversation]:
    result = await session.scalars(
        select(Conversation)
        .where(Conversation.tenant_id == tenant_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    return result.all()


async def conversation_messages(
    session: AsyncSession, tenant_id: str, conversation_id: str
) -> Sequence[Message]:
    await get_or_create_conversation(session, tenant_id, conversation_id, title="")
    result = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
    )
    return result.all()


async def conversation_history(
    session: AsyncSession, conversation_id: str, limit_turns: int
) -> list[ChatTurn]:
    result = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit_turns * 2)
    )
    rows = list(result.all())[::-1]
    return [
        ChatTurn(role="user" if m.role == "user" else "assistant", content=m.content) for m in rows
    ]


async def delete_conversation(session: AsyncSession, tenant_id: str, conversation_id: str) -> None:
    conversation = await get_or_create_conversation(session, tenant_id, conversation_id, title="")
    await session.execute(delete(Message).where(Message.conversation_id == conversation.id))
    await session.delete(conversation)


async def add_message(
    session: AsyncSession,
    conversation: Conversation,
    role: str,
    content: str,
    citations: list[dict[str, object]] | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation.id, role=role, content=content, citations=citations
    )
    session.add(message)
    conversation.updated_at = utcnow()
    await session.flush()
    return message
