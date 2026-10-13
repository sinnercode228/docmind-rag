"""Composition root: builds and owns every long-lived service for one app instance."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from docmind.config import Settings
from docmind.db import repositories as repo
from docmind.db.session import SessionFactory, create_engine, create_schema, create_session_factory
from docmind.embeddings.base import Embedder
from docmind.factories import build_embedder, build_llm, build_vector_store
from docmind.ingestion.pipeline import Fetcher, IngestionService
from docmind.jobs.runner import JobRunner
from docmind.llm.base import LLMProvider
from docmind.rag.service import RAGService
from docmind.retrieval.retriever import RetrievalParams, Retriever
from docmind.vectorstore.base import VectorStore

log = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine
    sessions: SessionFactory
    embedder: Embedder
    store: VectorStore
    llm: LLMProvider
    rag: RAGService
    ingestion: IngestionService
    jobs: JobRunner
    #: Ready documents queued by ``start()`` because their vectors were missing from the store.
    reindexing: int = 0

    async def start(self, *, run_jobs: bool = True) -> None:
        """Create the schema and bootstrap tenant, then start the ingestion workers.

        ``run_jobs=False`` is for one-shot commands that never wait for jobs (``create-tenant``):
        they would otherwise flip ready documents to ``queued`` and exit before reindexing them.
        """
        await create_schema(self.engine)
        if self.settings.bootstrap_api_key:
            async with self.sessions() as session:
                await repo.ensure_bootstrap_tenant(
                    session, self.settings.bootstrap_api_key.get_secret_value()
                )
                await session.commit()
        if not run_jobs:
            return
        self.reindexing = await self._queue_missing_vectors()
        self.jobs.start()
        async with self.sessions() as session:
            await self.jobs.recover(await repo.pending_job_ids(session))

    async def _queue_missing_vectors(self) -> int:
        """Create reindex jobs for ``ready`` documents whose vectors the store does not have.

        The in-memory store starts empty in every new process (and a snapshot can be stale),
        while SQLite still lists the documents as ``ready``. Their original bytes are kept in
        ``document_blobs``, so the index is rebuilt from the database. A tenant is reindexed
        when the store holds fewer chunks than its ready documents add up to.
        """
        queued = 0
        async with self.sessions() as session:
            for tenant_id, expected in (await repo.ready_chunk_totals(session)).items():
                stored = await self.store.count(tenant_id)
                if stored >= expected:
                    continue
                documents = await repo.ready_documents(session, tenant_id)
                for document in documents:
                    await repo.create_job(session, document)
                queued += len(documents)
                log.info(
                    "vector store has %d of %d chunks for tenant %s; re-indexing %d document(s)",
                    stored,
                    expected,
                    tenant_id,
                    len(documents),
                )
            await session.commit()
        return queued

    async def stop(self) -> None:
        await self.jobs.stop()
        await self.llm.aclose()
        await self.store.close()
        aclose = getattr(self.embedder, "aclose", None)
        if aclose is not None:
            await aclose()
        await self.engine.dispose()


async def build_container(
    settings: Settings,
    *,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
    llm: LLMProvider | None = None,
    fetcher: Fetcher | None = None,
) -> Container:
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    embedder = embedder or build_embedder(settings)
    store = store or await build_vector_store(settings)
    llm = llm or build_llm(settings)

    async def titles(tenant_id: str, ids: Sequence[str]) -> dict[str, str]:
        async with sessions() as session:
            return await repo.document_titles(session, tenant_id, ids)

    retriever = Retriever(
        embedder,
        store,
        RetrievalParams(
            top_k=settings.top_k,
            fetch_k=settings.fetch_k,
            mmr_lambda=settings.mmr_lambda,
            min_score=settings.min_score,
        ),
    )
    rag = RAGService(
        retriever,
        llm,
        titles,
        max_tokens=settings.llm_max_tokens,
        history_turns=settings.history_turns,
    )
    ingestion = IngestionService(
        sessions,
        embedder,
        store,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        fetcher=fetcher
        or IngestionService.default_fetcher(
            max_bytes=settings.max_upload_bytes,
            timeout_s=settings.url_fetch_timeout_s,
            allow_private=settings.allow_private_urls,
        ),
    )
    jobs = JobRunner(ingestion.run, workers=settings.ingest_workers)
    return Container(settings, engine, sessions, embedder, store, llm, rag, ingestion, jobs)
