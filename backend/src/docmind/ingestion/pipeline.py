"""Ingestion job handler: fetch -> extract -> chunk -> embed -> index, with status tracking."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from docmind.db import repositories as repo
from docmind.db.models import Document, Job
from docmind.db.session import SessionFactory
from docmind.embeddings.base import Embedder
from docmind.errors import DocMindError
from docmind.ingestion.chunking import chunk_document
from docmind.ingestion.fetch import FetchedResource, fetch_url
from docmind.ingestion.loaders import detect_mime_type, extract
from docmind.vectorstore.base import VectorStore

log = logging.getLogger(__name__)

Fetcher = Callable[[str], Awaitable[FetchedResource]]


class IngestionService:
    def __init__(
        self,
        sessions: SessionFactory,
        embedder: Embedder,
        store: VectorStore,
        *,
        chunk_size: int,
        chunk_overlap: int,
        fetcher: Fetcher,
    ) -> None:
        self._sessions = sessions
        self._embedder = embedder
        self._store = store
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._fetcher = fetcher

    @classmethod
    def default_fetcher(cls, *, max_bytes: int, timeout_s: float, allow_private: bool) -> Fetcher:
        async def _fetch(url: str) -> FetchedResource:
            return await fetch_url(
                url, max_bytes=max_bytes, timeout_s=timeout_s, allow_private=allow_private
            )

        return _fetch

    async def run(self, job_id: str) -> None:
        async with self._sessions() as session:
            job = await session.get(Job, job_id)
            if job is None or job.status in {"succeeded", "failed"}:
                return
            document = await session.get(Document, job.document_id)
            if document is None:
                await repo.mark_job(session, job_id, "failed", error="document deleted")
                await session.commit()
                return
            await repo.mark_job(session, job_id, "running")
            document.status = "processing"
            await session.commit()
            tenant_id, document_id = document.tenant_id, document.id

        try:
            chunk_count, title, mime = await self._process(tenant_id, document_id)
        except DocMindError as exc:
            await self._fail(job_id, document_id, exc.message)
        except Exception as exc:  # unexpected: log with traceback, hide internals from users
            log.exception("ingestion job %s crashed", job_id)
            await self._fail(job_id, document_id, f"Internal error ({type(exc).__name__})")
        else:
            async with self._sessions() as session:
                document = await session.get(Document, document_id)
                if document is not None:
                    document.status = "ready"
                    document.chunk_count = chunk_count
                    document.title = title
                    document.mime_type = mime
                    document.error = None
                await repo.mark_job(session, job_id, "succeeded")
                await session.commit()
            log.info("indexed %s: %d chunks", document_id, chunk_count)

    async def _process(self, tenant_id: str, document_id: str) -> tuple[int, str, str]:
        async with self._sessions() as session:
            document = await session.get(Document, document_id)
            assert document is not None
            data = await repo.get_blob(session, document_id)
            source_type, source, title = document.source_type, document.source, document.title
            declared_mime = document.mime_type

            if data is None and source_type == "url":
                fetched = await self._fetcher(source)
                data = fetched.data
                declared_mime = detect_mime_type(fetched.url, fetched.content_type, data)
                await repo.save_blob(session, document_id, data)
                document.size_bytes = len(data)
                await session.commit()
            if data is None:
                raise DocMindError("Document has no content to index")

        mime = declared_mime or detect_mime_type(source, None, data)
        filename = source if source_type == "upload" else None
        extracted = await asyncio.to_thread(extract, data, mime_type=mime, filename=filename)
        chunks = chunk_document(
            extracted,
            document_id,
            chunk_size=self._chunk_size,
            chunk_overlap=self._chunk_overlap,
        )
        embeddings = await self._embedder.embed_documents([c.text for c in chunks])
        await self._store.delete_document(tenant_id, document_id)
        await self._store.upsert(tenant_id, chunks, embeddings)
        keep_title = source_type == "text" or (source_type == "upload" and title != source)
        final_title = title if keep_title else extracted.title or title
        return len(chunks), final_title, mime

    async def _fail(self, job_id: str, document_id: str, message: str) -> None:
        async with self._sessions() as session:
            document = await session.get(Document, document_id)
            if document is not None:
                document.status = "failed"
                document.error = message
            await repo.mark_job(session, job_id, "failed", error=message)
            await session.commit()
