"""The scheduled fetch: the budget, the rotation, and the ledger.

Against a fake provider and a real database, because every decision the
scheduler makes is a database read — testing it against a stubbed repository
would test the stub. There is no timing here: `scheduler_loop` is a sleep around
`run_one_fetch`, and it is `run_one_fetch` that holds the rules.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import TracebackType

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.integrations.jobs.fake import FakeJobProvider
from app.models.job_fetch import JobFetchRun
from app.repositories.job_fetch import JobFetchRunRepository
from app.workers import job_fetch_scheduler


class _TestSessionFactory:
    """Hand the scheduler the test's session, and refuse to close it.

    `run_one_fetch` owns its session — it opens one and lets the `async with`
    close it — which is right in production and wrong here: closing would end
    the transaction the fixture rolls back at teardown. `__aexit__` therefore
    does nothing, so the code under test still commits (into a savepoint) and
    the test still sees the rows.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def __call__(self) -> _TestSessionFactory:
        return self

    async def __aenter__(self) -> AsyncSession:
        return self.session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False


@pytest.fixture
def settings() -> Settings:
    # Every value the scheduler reads is pinned here rather than inherited.
    # The developer's own .env is loaded in this container, so a test that let
    # `jobs_auto_fetch_enabled` come from it would pass or fail depending on
    # whether the feature happened to be switched on locally.
    return get_settings().model_copy(
        update={
            "jobs_auto_fetch_enabled": False,
            "jobs_auto_fetch_per_day": 6,
            "jobs_auto_fetch_exhausted_per_day": 1,
            "jobs_fetch_country": "in",
        }
    )


@pytest.fixture
def scheduler(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> Callable[[FakeJobProvider], None]:
    """Point the scheduler at this test's session, and at a provider it names."""
    monkeypatch.setattr(
        job_fetch_scheduler, "get_session_factory", lambda: _TestSessionFactory(db_session)
    )

    def use(provider: FakeJobProvider) -> None:
        monkeypatch.setattr(job_fetch_scheduler, "get_job_provider", lambda: provider)

    return use


class TestOneTick:
    async def test_fetches_and_writes_the_run_down(
        self,
        db_session: AsyncSession,
        settings: Settings,
        scheduler: Callable[[FakeJobProvider], None],
        seeded_skills: int,
    ) -> None:
        provider = FakeJobProvider()
        scheduler(provider)

        assert await job_fetch_scheduler.run_one_fetch(settings) is True
        assert provider.calls == 1

        run = await db_session.scalar(select(JobFetchRun))
        assert run is not None
        assert run.scheduled is True
        assert run.requests_spent == 1
        assert run.created == 2
        # The query came from the rotation, not from a caller.
        assert run.query in job_fetch_scheduler.build_queries()

    async def test_does_nothing_without_a_provider(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(job_fetch_scheduler, "get_job_provider", lambda: None)

        assert await job_fetch_scheduler.run_one_fetch(settings) is False


class TestBudget:
    async def test_stops_once_the_day_is_spent(
        self,
        settings: Settings,
        scheduler: Callable[[FakeJobProvider], None],
        seeded_skills: int,
    ) -> None:
        provider = FakeJobProvider(pages=[[]])
        scheduler(provider)
        one_a_day = settings.model_copy(update={"jobs_auto_fetch_per_day": 1})

        assert await job_fetch_scheduler.run_one_fetch(one_a_day) is True
        assert await job_fetch_scheduler.run_one_fetch(one_a_day) is False

        # Not merely "returned False": no second request left the process. The
        # whole point of the budget is quota, not tidiness.
        assert provider.calls == 1

    async def test_a_restart_does_not_reset_the_budget(
        self,
        db_session: AsyncSession,
        settings: Settings,
        scheduler: Callable[[FakeJobProvider], None],
    ) -> None:
        """The count is read from the database, so an empty process is not an empty day.

        A counter held in memory would let a container restart — or a dev
        reload — spend the whole allowance again, and quota does not come back.
        """
        provider = FakeJobProvider()
        scheduler(provider)
        await JobFetchRunRepository(db_session).record(
            query="python developer in Pune",
            country="in",
            requests_spent=6,
            created=10,
            duplicates=0,
            failed=0,
            quota_remaining=120,
            scheduled=True,
            stop_reason=None,
        )

        assert await job_fetch_scheduler.run_one_fetch(settings) is False
        assert provider.calls == 0

    async def test_yesterdays_spending_does_not_count(
        self,
        db_session: AsyncSession,
        settings: Settings,
        scheduler: Callable[[FakeJobProvider], None],
        seeded_skills: int,
    ) -> None:
        provider = FakeJobProvider(pages=[[]])
        scheduler(provider)
        run = await JobFetchRunRepository(db_session).record(
            query="python developer in Pune",
            country="in",
            requests_spent=6,
            created=0,
            duplicates=0,
            failed=0,
            quota_remaining=120,
            scheduled=True,
            stop_reason=None,
        )
        run.started_at = datetime.now(UTC) - timedelta(days=1)
        await db_session.flush()

        assert await job_fetch_scheduler.run_one_fetch(settings) is True

    async def test_a_manual_fetch_counts_against_the_same_budget(
        self,
        db_session: AsyncSession,
        settings: Settings,
        scheduler: Callable[[FakeJobProvider], None],
    ) -> None:
        """One quota, one ledger. An admin's run is `scheduled=False`, not a separate book."""
        provider = FakeJobProvider()
        scheduler(provider)
        await JobFetchRunRepository(db_session).record(
            query="anything an admin typed",
            country="in",
            requests_spent=6,
            created=3,
            duplicates=0,
            failed=0,
            quota_remaining=100,
            scheduled=False,
            stop_reason=None,
        )

        assert await job_fetch_scheduler.run_one_fetch(settings) is False


class TestRotation:
    async def test_consecutive_ticks_ask_different_questions(
        self,
        settings: Settings,
        scheduler: Callable[[FakeJobProvider], None],
        seeded_skills: int,
    ) -> None:
        """Repeating a query returns the same jobs, so repeating one is a wasted request."""
        provider = FakeJobProvider(pages=[[]])
        scheduler(provider)

        for _ in range(3):
            assert await job_fetch_scheduler.run_one_fetch(settings) is True

        asked = [search["query"] for search in provider.searches]
        assert len(set(asked)) == 3

    async def test_an_exhausted_rotation_drops_to_a_trickle(
        self,
        settings: Settings,
        scheduler: Callable[[FakeJobProvider], None],
        monkeypatch: pytest.MonkeyPatch,
        seeded_skills: int,
    ) -> None:
        """Once every query has been asked, repeats yield little — so spend far less.

        Stopping altogether would be wrong: the index does keep growing, just
        slowly. One request a day is the honest rate for a slow index.
        """
        provider = FakeJobProvider(pages=[[]])
        scheduler(provider)
        monkeypatch.setattr(
            job_fetch_scheduler, "build_queries", lambda: ["python developer in Pune"]
        )

        assert await job_fetch_scheduler.run_one_fetch(settings) is True
        # The day's budget is 6 and only one request has been spent, so it is
        # exhaustion — not the budget — that stops the second.
        assert await job_fetch_scheduler.run_one_fetch(settings) is False
        assert provider.calls == 1


class TestStart:
    def test_starts_nothing_when_switched_off(self, settings: Settings) -> None:
        assert job_fetch_scheduler.start(settings) is None

    def test_declines_to_start_without_a_provider(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Enabled but unconfigured is a misconfiguration, not a reason to loop uselessly."""
        monkeypatch.setattr(job_fetch_scheduler, "get_job_provider", lambda: None)
        enabled = settings.model_copy(update={"jobs_auto_fetch_enabled": True})

        assert job_fetch_scheduler.start(enabled) is None
