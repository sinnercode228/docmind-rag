"""Vectors in the default in-memory store do not outlive a process; the database does.

Each test runs two separate ``Container`` instances over one SQLite file, the way
``docmind ingest`` and ``docmind ask`` (or two runs of ``make api``) do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docmind.cli import cmd_ask, cmd_create_tenant, cmd_ingest
from docmind.config import Settings
from docmind.container import build_container
from docmind.db import repositories as repo
from docmind.rag.service import DoneEvent, SourcesEvent
from tests.conftest import API_KEY, FIXTURES


@pytest.fixture
def file_settings(settings: Settings, tmp_path: Path) -> Settings:
    assert settings.vector_store == "memory"
    assert settings.memory_store_path is None
    return settings.model_copy(
        update={"database_url": f"sqlite+aiosqlite:///{tmp_path / 'docmind.db'}"}
    )


async def test_second_container_reindexes_ready_documents(
    file_settings: Settings, handbook_md: bytes
) -> None:
    first = await build_container(file_settings)
    await first.start()
    try:
        async with first.sessions() as session:
            tenant = await repo.ensure_bootstrap_tenant(session, API_KEY)
            document, job = await repo.add_document(
                session,
                tenant_id=tenant.id,
                title="handbook.md",
                source_type="upload",
                source="handbook.md",
                mime_type="text/markdown",
                data=handbook_md,
            )
            await session.commit()
        await first.jobs.enqueue(job.id)
        await first.jobs.join()
        chunk_count = await first.store.count(tenant.id)
        assert chunk_count > 0
    finally:
        await first.stop()

    second = await build_container(file_settings)
    await second.start()
    try:
        await second.jobs.join()
        assert await second.store.count(tenant.id) == chunk_count
        assert second.reindexing == 1
        async with second.sessions() as session:
            again = await repo.get_document(session, tenant.id, document.id)
        assert again.status == "ready"
        assert again.chunk_count == chunk_count

        question = "How many vacation days do employees get?"
        events = [e async for e in second.rag.stream_answer(tenant.id, question)]
        sources = next(e for e in events if isinstance(e, SourcesEvent))
        done = events[-1]
        assert sources.citations
        assert isinstance(done, DoneEvent)
        assert "25 working days" in done.answer
    finally:
        await second.stop()

    third = await build_container(file_settings)
    await third.start()
    try:
        # Every new process rebuilds the index once, and nothing is left pending after it.
        assert third.reindexing == 1
        await third.jobs.join()
        assert await third.store.count(tenant.id) == chunk_count
        async with third.sessions() as session:
            assert await repo.pending_job_ids(session) == []
    finally:
        await third.stop()


async def test_snapshot_that_is_complete_is_not_reindexed(
    file_settings: Settings, tmp_path: Path, handbook_md: bytes
) -> None:
    snapshot = file_settings.model_copy(update={"memory_store_path": str(tmp_path / "vectors")})
    first = await build_container(snapshot)
    await first.start()
    try:
        async with first.sessions() as session:
            tenant = await repo.ensure_bootstrap_tenant(session, API_KEY)
            _, job = await repo.add_document(
                session,
                tenant_id=tenant.id,
                title="handbook.md",
                source_type="upload",
                source="handbook.md",
                mime_type="text/markdown",
                data=handbook_md,
            )
            await session.commit()
        await first.jobs.enqueue(job.id)
        await first.jobs.join()
    finally:
        await first.stop()

    second = await build_container(snapshot)
    await second.start()
    try:
        assert await second.store.count(tenant.id) > 0
        assert second.reindexing == 0
    finally:
        await second.stop()


async def test_cli_ingest_then_ask_in_separate_runs(
    file_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    await cmd_ingest(file_settings, API_KEY, [FIXTURES / "handbook.md"])
    ingested = capsys.readouterr()
    await cmd_ask(file_settings, API_KEY, "How many vacation days do employees get?")
    asked = capsys.readouterr()

    assert "25 working days" in asked.out
    assert "*[1] Lumenfold Labs Employee Handbook" in asked.out
    assert "ready" in ingested.out
    assert "DOCMIND_MEMORY_STORE_PATH" in ingested.err
    assert "re-indexing 1 document" in asked.err


async def test_create_tenant_leaves_ready_documents_alone(
    file_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    await cmd_ingest(file_settings, API_KEY, [FIXTURES / "handbook.md"])
    await cmd_create_tenant(file_settings, "second")
    assert "api_key:" in capsys.readouterr().out

    container = await build_container(file_settings)
    try:
        async with container.sessions() as session:
            tenant = await repo.tenant_for_key(session, API_KEY)
            assert tenant is not None
            statuses = [d.status for d in await repo.list_documents(session, tenant.id)]
            assert statuses == ["ready"]
            assert await repo.pending_job_ids(session) == []
    finally:
        await container.stop()
