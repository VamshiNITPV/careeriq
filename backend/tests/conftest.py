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
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
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

from app.api.deps import (  # noqa: E402
    get_jobs_provider,
    get_notification_service,
    get_pipeline_runner,
    get_storage,
)
from app.core.database import dispose_engine, get_db_session  # noqa: E402
from app.integrations.email import CapturingEmailProvider  # noqa: E402
from app.integrations.jobs.fake import FakeJobProvider  # noqa: E402
from app.integrations.storage import LocalObjectStorage  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.notifications import NotificationService  # noqa: E402
from app.services.resume.pipeline import (  # noqa: E402
    process_resume_version,
    seed_skill_taxonomy,
)

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


@pytest.fixture(autouse=True)
async def _dispose_global_engine() -> AsyncGenerator[None]:
    """Drop the process-wide engine after each test.

    Anything reaching for it — the readiness probe, for instance — would
    otherwise bind it to the first test's event loop and then fail in every
    later test with "attached to a different loop". Disposing means each test
    gets an engine on its own loop.
    """
    yield
    await dispose_engine()


@pytest.fixture
def job_provider() -> FakeJobProvider:
    """A jobs provider that makes no network calls.

    Overriding the dependency is what keeps the suite offline even when the
    developer's .env holds a real API key. A test that needs different pages or
    a quota error builds its own FakeJobProvider and overrides again.
    """
    return FakeJobProvider()


@pytest.fixture
def storage(tmp_path: Path) -> LocalObjectStorage:
    """Object storage rooted in a per-test temporary directory.

    Never the configured upload path: a test run must not write into, or delete
    from, a real storage location.
    """
    return LocalObjectStorage(tmp_path / "uploads")


@pytest.fixture
async def seeded_skills(db_session: AsyncSession) -> int:
    """Load the skill taxonomy into the test transaction.

    Opt-in rather than autouse — most tests do not need ~150 rows inserted, and
    the ones that do say so.
    """
    return await seed_skill_taxonomy(db_session)


@pytest.fixture
def run_pipeline(
    db_session: AsyncSession, storage: LocalObjectStorage
) -> Callable[[uuid.UUID], Awaitable[object]]:
    """Run the resume pipeline against this test's session and storage.

    Injected rather than left to the process-wide defaults: the rows under test
    live in an uncommitted transaction that a separate connection cannot see,
    and the uploaded file is in a temporary directory, not the configured store.
    """

    async def _run(version_id: uuid.UUID) -> object:
        return await process_resume_version(version_id, session=db_session, storage=storage)

    return _run


@pytest.fixture
def emails() -> CapturingEmailProvider:
    """Captures every email the app tries to send.

    Asserting on real message content — that a reset link is present, that a
    security notice went to the right address — is far more useful than
    asserting an SMTP call happened. It also keeps the suite offline.
    """
    return CapturingEmailProvider()


@pytest.fixture
async def client(
    db_session: AsyncSession,
    emails: CapturingEmailProvider,
    storage: LocalObjectStorage,
    job_provider: FakeJobProvider,
) -> AsyncGenerator[AsyncClient]:
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
    app.dependency_overrides[get_notification_service] = lambda: NotificationService(emails)
    app.dependency_overrides[get_storage] = lambda: storage
    # The suite must never reach the internet. This override is what
    # guarantees it even on a machine whose .env holds a real JOBS_API_KEY —
    # Settings reads .env regardless of ENVIRONMENT=test.
    app.dependency_overrides[get_jobs_provider] = lambda: job_provider

    # Tests drive the pipeline explicitly via the run_pipeline fixture, which
    # injects this test's session and storage. Left in place, the real
    # background task would run on the global engine, fail to find rows that
    # live in an uncommitted transaction, and log an ERROR on every upload.
    async def no_background_pipeline(_version_id: uuid.UUID) -> None:
        return None

    app.dependency_overrides[get_pipeline_runner] = lambda: no_background_pipeline

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
