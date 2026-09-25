from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from docmind.db.models import Base

SessionFactory = async_sessionmaker[AsyncSession]


def create_engine(url: str) -> AsyncEngine:
    if url.startswith("sqlite"):
        kwargs: dict[str, object] = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool  # share one in-memory DB across sessions
        engine = create_async_engine(url, **kwargs)
        _enable_sqlite_fks(engine.sync_engine)
        return engine
    return create_async_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)


def _enable_sqlite_fks(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_session_factory(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    """Create tables if missing. (A production rollout would use Alembic migrations.)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
