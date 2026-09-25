from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy import text

from docmind import __version__
from docmind.api.deps import ContainerDep, SessionDep, TenantDep, require_admin
from docmind.api.schemas import MeOut, TenantCreate, TenantCreated, TenantOut
from docmind.db import repositories as repo

router = APIRouter(tags=["system"])


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/readyz", summary="Readiness probe (database + workers)")
async def readyz(session: SessionDep, container: ContainerDep) -> dict[str, Any]:
    await session.execute(text("SELECT 1"))
    return {
        "status": "ready",
        "workers": container.jobs.running,
        "llm": container.llm.name,
        "embedder": container.embedder.name,
        "vector_store": container.settings.vector_store,
    }


@router.get("/v1/me", response_model=MeOut, summary="Current tenant and index stats")
async def me(tenant: TenantDep, session: SessionDep, container: ContainerDep) -> MeOut:
    stats = await repo.tenant_stats(session, tenant.id)
    return MeOut(
        tenant=TenantOut.model_validate(tenant),
        documents=stats["documents"],
        chunks=stats["chunks"],
        llm=container.llm.name,
        embedder=container.embedder.name,
    )


@router.post(
    "/v1/admin/tenants",
    response_model=TenantCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
    tags=["admin"],
    summary="Create a tenant (isolated knowledge base) and its first API key",
)
async def create_tenant(body: TenantCreate, session: SessionDep) -> TenantCreated:
    tenant, raw_key = await repo.create_tenant(session, body.name, label="admin-api")
    await session.commit()
    return TenantCreated(tenant=TenantOut.model_validate(tenant), api_key=raw_key)
