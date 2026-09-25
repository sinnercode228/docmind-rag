"""FastAPI dependencies: container access, DB sessions, API-key and admin auth."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from docmind.container import Container
from docmind.db import repositories as repo
from docmind.db.models import Tenant

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="Tenant API key")
bearer = HTTPBearer(auto_error=False, description="Tenant API key as a Bearer token")


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


async def get_session(container: ContainerDep) -> AsyncIterator[AsyncSession]:
    async with container.sessions() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_tenant(
    session: SessionDep,
    api_key: Annotated[str | None, Depends(api_key_header)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Tenant:
    raw = api_key or (credentials.credentials if credentials else None)
    if not raw:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key (X-API-Key header or Bearer token)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    tenant = await repo.tenant_for_key(session, raw)
    if tenant is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")
    return tenant


TenantDep = Annotated[Tenant, Depends(get_tenant)]


def require_admin(
    container: ContainerDep, x_admin_token: Annotated[str | None, Header()] = None
) -> None:
    expected = container.settings.admin_token
    if expected is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Admin API is disabled")
    if not x_admin_token or not hmac.compare_digest(
        x_admin_token.encode(), expected.get_secret_value().encode()
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid admin token")
