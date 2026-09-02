"""Async SQLAlchemy engine, session factory, and the FastAPI session dependency.

Per ADR-004 and architecture.md §2, this module is the only place that builds a
session. Repositories receive one; services never construct one; routers never
touch one directly.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide engine, creating it on first use.

    Lazy rather than module-level so that importing this module does not open
    connections. That matters for Alembic, for tests, and for Cloud Run cold
    starts where import time is on the critical path (ADR-011).
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.database_echo,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            # Recycle before typical proxy/firewall idle timeouts, otherwise the
            # first query after an idle period fails on a silently dead socket.
            pool_recycle=1800,
            # Validate a connection before handing it out. Costs a round trip;
            # prevents serving an error from a connection the server already closed.
            pool_pre_ping=True,
        )
        log.debug("database engine created", pool_size=settings.database_pool_size)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            # Objects stay usable after commit. With the default (True), touching
            # any attribute post-commit triggers a lazy refresh — which raises in
            # async code because the implicit IO has no await point.
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency yielding a session scoped to one request.

    The transaction boundary is the request. A handler that returns normally
    commits; one that raises rolls back. Services therefore do not need to
    manage transactions themselves for the common case.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_database_health() -> dict[str, Any]:
    """Readiness probe support. Never raises — returns the failure as data.

    A readiness endpoint that raises produces a 500 with no detail about which
    dependency is down, which is the opposite of what a probe is for.
    """
    from sqlalchemy import text

    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 - health checks report, never propagate
        log.warning("database health check failed", error=str(exc))
        return {"status": "error", "detail": type(exc).__name__}


async def dispose_engine() -> None:
    """Close all pooled connections. Called on application shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        log.debug("database engine disposed")
    _engine = None
    _session_factory = None
