from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status

from docmind.api.deps import ContainerDep, SessionDep, TenantDep
from docmind.api.schemas import (
    DocumentOut,
    IngestAccepted,
    JobOut,
    TextIngest,
    UrlIngest,
)
from docmind.db import repositories as repo
from docmind.errors import DocMindError, DocumentTooLargeError
from docmind.ingestion.loaders import MARKDOWN, PLAIN, detect_mime_type

router = APIRouter(prefix="/v1", tags=["documents"])

_READ_CHUNK = 1024 * 1024


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    buffer = bytearray()
    while piece := await upload.read(_READ_CHUNK):
        buffer.extend(piece)
        if len(buffer) > limit:
            raise DocumentTooLargeError(f"File exceeds the {limit // (1024 * 1024)} MB limit")
    return bytes(buffer)


@router.post(
    "/documents",
    response_model=IngestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a PDF, DOCX, Markdown, HTML or text file for background ingestion",
)
async def upload_document(
    tenant: TenantDep,
    session: SessionDep,
    container: ContainerDep,
    file: Annotated[UploadFile, File(description="Document file")],
    title: Annotated[str | None, Form(max_length=500)] = None,
) -> IngestAccepted:
    data = await _read_limited(file, container.settings.max_upload_bytes)
    if not data:
        raise DocMindError("Uploaded file is empty")
    filename = file.filename or "upload"
    mime = detect_mime_type(filename, file.content_type, data)
    document, job = await repo.add_document(
        session,
        tenant_id=tenant.id,
        title=title or filename,
        source_type="upload",
        source=filename,
        mime_type=mime,
        data=data,
    )
    await session.commit()
    await container.jobs.enqueue(job.id)
    return IngestAccepted(
        document=DocumentOut.model_validate(document), job=JobOut.model_validate(job)
    )


@router.post(
    "/documents/url",
    response_model=IngestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a web page or remote PDF by URL",
)
async def ingest_url(
    body: UrlIngest, tenant: TenantDep, session: SessionDep, container: ContainerDep
) -> IngestAccepted:
    url = str(body.url)
    document, job = await repo.add_document(
        session,
        tenant_id=tenant.id,
        title=body.title or url,
        source_type="url",
        source=url,
        mime_type=None,
        data=None,
    )
    await session.commit()
    await container.jobs.enqueue(job.id)
    return IngestAccepted(
        document=DocumentOut.model_validate(document), job=JobOut.model_validate(job)
    )


@router.post(
    "/documents/text",
    response_model=IngestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest raw Markdown or plain text",
)
async def ingest_text(
    body: TextIngest, tenant: TenantDep, session: SessionDep, container: ContainerDep
) -> IngestAccepted:
    data = body.text.encode()
    document, job = await repo.add_document(
        session,
        tenant_id=tenant.id,
        title=body.title,
        source_type="text",
        source=body.title,
        mime_type=MARKDOWN if body.format == "markdown" else PLAIN,
        data=data,
    )
    await session.commit()
    await container.jobs.enqueue(job.id)
    return IngestAccepted(
        document=DocumentOut.model_validate(document), job=JobOut.model_validate(job)
    )


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(tenant: TenantDep, session: SessionDep) -> list[DocumentOut]:
    return [DocumentOut.model_validate(d) for d in await repo.list_documents(session, tenant.id)]


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: str, tenant: TenantDep, session: SessionDep) -> DocumentOut:
    return DocumentOut.model_validate(await repo.get_document(session, tenant.id, document_id))


@router.post(
    "/documents/{document_id}/reindex",
    response_model=IngestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run ingestion (e.g. after changing the embedder or chunking settings)",
)
async def reindex_document(
    document_id: str, tenant: TenantDep, session: SessionDep, container: ContainerDep
) -> IngestAccepted:
    document = await repo.get_document(session, tenant.id, document_id)
    job = await repo.create_job(session, document)
    await session.commit()
    await container.jobs.enqueue(job.id)
    return IngestAccepted(
        document=DocumentOut.model_validate(document), job=JobOut.model_validate(job)
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str, tenant: TenantDep, session: SessionDep, container: ContainerDep
) -> None:
    await repo.delete_document(session, tenant.id, document_id)
    await session.commit()
    await container.store.delete_document(tenant.id, document_id)


@router.get("/jobs/{job_id}", response_model=JobOut, tags=["jobs"])
async def get_job(job_id: str, tenant: TenantDep, session: SessionDep) -> JobOut:
    return JobOut.model_validate(await repo.get_job(session, tenant.id, job_id))
