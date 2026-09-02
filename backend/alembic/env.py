"""Alembic migration environment.

Runs migrations through the async engine rather than adding psycopg2 purely for
Alembic. One driver means one connection code path and one set of failure modes.

The URL comes from application settings, not alembic.ini, so the DSN has a single
source of truth and no connection string is committed.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

# Importing the package registers every model on Base.metadata. Without this,
# autogenerate would see an empty schema and emit migrations dropping every table.
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    return get_settings().database_url


def _include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Filter objects out of autogenerate.

    pgvector creates internal tables and extensions own their types; without
    this, autogenerate proposes dropping things it did not create.
    """
    if type_ == "table" and name in {"spatial_ref_sys"}:
        return False
    return True


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting.

    Used to review the exact DDL before it runs against a managed database
    where an accidental lock is expensive.
    """
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Without compare_type, a column changing from VARCHAR(50) to VARCHAR(200)
        # produces no migration and the mismatch is found in production.
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # NullPool: a migration run is a single short-lived connection. Pooling adds
    # nothing and leaves connections open after the command finishes.
    connectable = create_async_engine(_get_url(), poolclass=pool.NullPool)
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
