"""ASGI entrypoint: ``uvicorn docmind.main:create_app --factory``."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from docmind import __version__
from docmind.api import routes_chat, routes_documents, routes_system
from docmind.config import Settings, get_settings
from docmind.container import Container, build_container
from docmind.errors import DocMindError

DESCRIPTION = """
DocMind is a multi-tenant retrieval-augmented generation (RAG) service: upload PDFs, DOCX,
Markdown or web pages, then ask questions and get streamed answers with numbered citations.

Authenticate with a tenant API key via `X-API-Key: dm_...` or `Authorization: Bearer dm_...`.

_DocMind is a fictional demo brand. Демо-проект._
"""


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or (container.settings if container else get_settings())
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        instance = container or await build_container(settings)
        app.state.container = instance
        await instance.start()
        try:
            yield
        finally:
            await instance.stop()

    app = FastAPI(
        title="DocMind API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DocMindError)
    async def _docmind_error(_: Request, exc: DocMindError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"error": exc.code, "message": exc.message}
        )

    app.include_router(routes_system.router)
    app.include_router(routes_documents.router)
    app.include_router(routes_chat.router)
    return app
