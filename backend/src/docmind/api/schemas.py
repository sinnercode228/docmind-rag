from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TenantOut(ORM):
    id: str
    name: str
    created_at: datetime


class MeOut(BaseModel):
    tenant: TenantOut
    documents: int
    chunks: int
    llm: str
    embedder: str


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TenantCreated(BaseModel):
    tenant: TenantOut
    api_key: str = Field(description="Shown once. Store it securely.")


class DocumentOut(ORM):
    id: str
    title: str
    source_type: str
    source: str
    mime_type: str | None
    size_bytes: int
    status: Literal["queued", "processing", "ready", "failed"]
    error: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class JobOut(ORM):
    id: str
    document_id: str
    kind: str
    status: Literal["queued", "running", "succeeded", "failed"]
    error: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class IngestAccepted(BaseModel):
    document: DocumentOut
    job: JobOut


class UrlIngest(BaseModel):
    url: HttpUrl
    title: str | None = Field(default=None, max_length=500)


class TextIngest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=2_000_000)
    format: Literal["markdown", "text"] = "markdown"


class CitationOut(BaseModel):
    index: int
    document_id: str
    document_title: str
    chunk_id: str
    snippet: str
    score: float
    page: int | None = None
    heading: str | None = None
    highlight: list[int] | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    document_ids: list[str] | None = None


class SearchResponse(BaseModel):
    results: list[CitationOut]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)
    document_ids: list[str] | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    message_id: str
    answer: str
    citations: list[CitationOut]
    cited: list[int]
    model: str
    stop_reason: str


class ConversationOut(ORM):
    id: str
    title: str
    channel: str
    created_at: datetime
    updated_at: datetime


class MessageOut(ORM):
    id: str
    role: Literal["user", "assistant"]
    content: str
    citations: list[dict[str, Any]] | None
    created_at: datetime


class ErrorOut(BaseModel):
    error: str
    message: str
