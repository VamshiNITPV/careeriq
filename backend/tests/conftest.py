"""Shared test fixtures.

The environment is redirected to `careeriq_test` **before any application module
is imported**, because `get_settings()` is `lru_cache`d — once it has read the
development DSN, nothing later can change it. Hence the `os.environ` writes at
module top rather than inside a fixture.

Schema is built by running the real Alembic migrations rather than
`Base.metadata.create_all`. Two reasons: the models declare enums with
`create_type=False`, so `create_all` would fail on missing types; and running
the migrations means every test run also exercises the migration path, so a
broken migration fails the suite instead of surviving until deployment.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _test_database_url() -> str:
    """Point at careeriq_test on the same server as the configured database."""
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://careeriq:careeriq_dev_password@localhost:5432/careeriq",
    )
    base, _, _ = url.rpartition("/")
    return f"{base}/careeriq_test"


# Must happen before app imports. Ruff would move these below the imports if
# they were written after them, hence the explicit ordering here.
os.environ["DATABASE_URL"] = _test_database_url()
os.environ["ENVIRONMENT"] = "test"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ.setdefault(
    "JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-to-pass-validation-0123456789"
)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.database import get_db_session  # noqa: E402
from app.main import create_app  # noqa: E402

TEST_DATABASE_URL = os.environ["DATABASE_URL"]
API = "/api/v1"


@pytest.fixture(scope="session", autouse=True)
def _prepare_schema() -> None:
    """Drop and rebuild the test schema once per run.

    Deliberately a *sync* fixture: Alembic's async env.py calls `asyncio.run`,
    which raises if a loop is already running. A sync fixture has no running
    loop, so both this and Alembic can use `asyncio.run` safely.
    """

    async def reset() -> None:
        # AUTOCOMMIT: DROP SCHEMA cannot run inside a transaction block.
        engine = create_async_engine(
            TEST_DATABASE_URL, poolclass=NullPool, isolation_level="AUTOCOMMIT"
        )
        try:
            async with engine.connect() as conn:
                await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
                await conn.execute(text("CREATE SCHEMA public"))
        finally:
            await engine.dispose()

    asyncio.run(reset())

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(config, "head")


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    """A session whose writes are rolled back at the end of the test.

    The outer connection holds a transaction that is never committed;
    `join_transaction_mode="create_savepoint"` turns the application's own
    `commit()` calls into savepoint releases inside it. So the code under test
    genuinely commits — the commit path is exercised, not bypassed — and the
    final rollback still discards everything. Tests stay isolated without the
    cost of rebuilding the schema between them.
    """
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    connection = await engine.connect()
    transaction = await connection.begin()

    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        await session.close()
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    """HTTP client wired to the app, sharing the test's rolled-back session.

    ASGITransport dispatches in-process: no port is bound and no network call is
    made, so the suite runs anywhere and cannot be flaky because a port was busy.
    """
    app = create_app()

    async def override_session() -> AsyncGenerator[AsyncSession]:
        """Mirror the real dependency's transaction semantics.

        This must commit on success and roll back on failure exactly as
        `get_db_session` does. An override that merely yields the session lets
        writes survive a request that raised, which production would have rolled
        back — so a whole class of bug (a side effect that must persist across a
        failure) passes in tests and breaks live. Savepoint mode means these
        commits are still discarded by the outer rollback after the test.
        """
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db_session] = override_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client:
        yield http_client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------- helpers
@pytest.fixture
def user_payload() -> dict[str, str]:
    return {
        "email": "priya@example.com",
        "password": "correct-horse-9",
        "full_name": "Priya S.",
    }


@pytest.fixture
async def registered_user(client: AsyncClient, user_payload: dict[str, str]) -> dict[str, object]:
    """Register a user and return the parsed response body."""
    response = await client.post(f"{API}/auth/register", json=user_payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def auth_headers(registered_user: dict[str, object]) -> dict[str, str]:
    tokens = registered_user["tokens"]  # type: ignore[index]
    return {"Authorization": f"Bearer {tokens['access_token']}"}  # type: ignore[index]
