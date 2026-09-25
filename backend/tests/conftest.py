from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from docmind.config import Settings
from docmind.container import Container, build_container
from docmind.ingestion.fetch import FetchedResource
from docmind.main import create_app

API_KEY = "dm_test_key_tenant_a"
ADMIN_TOKEN = "admin-secret-token"
FIXTURES = Path(__file__).parent / "fixtures"

REMOTE_PAGES: dict[str, tuple[bytes, str]] = {
    "https://docs.example.com/security": (
        b"<html><head><title>Security Policy</title></head><body><main>"
        b"<h1>Security Policy</h1><h2>Passwords</h2>"
        b"<p>Passwords must be rotated every 90 days and contain at least 14 characters.</p>"
        b"<h2>Laptops</h2><p>Laptops must use full-disk encryption at all times.</p>"
        b"<script>alert('x')</script></main></body></html>",
        "text/html; charset=utf-8",
    )
}


async def fake_fetcher(url: str) -> FetchedResource:
    if url not in REMOTE_PAGES:
        from docmind.errors import UnsafeURLError

        raise UnsafeURLError("URL resolves to a private or reserved address")
    data, content_type = REMOTE_PAGES[url]
    return FetchedResource(url=url, data=data, content_type=content_type)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        bootstrap_api_key=API_KEY,  # type: ignore[arg-type]
        admin_token=ADMIN_TOKEN,  # type: ignore[arg-type]
        llm_provider="fake",
        embedder="hashing",
        vector_store="memory",
        ingest_workers=1,
        chunk_size=400,
        chunk_overlap=60,
        max_upload_mb=1,
    )


@pytest.fixture
async def container(settings: Settings) -> AsyncIterator[Container]:
    instance = await build_container(settings, fetcher=fake_fetcher)
    yield instance


@pytest.fixture
async def app(settings: Settings, container: Container) -> AsyncIterator[FastAPI]:
    application = create_app(settings, container)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"X-API-Key": API_KEY}
    ) as http:
        yield http


@pytest.fixture
def handbook_md() -> bytes:
    return (FIXTURES / "handbook.md").read_bytes()
