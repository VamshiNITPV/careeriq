"""Keep the job corpus growing without anyone pressing a button.

**Scope.** One recurring task, not a task queue. ADR-008 and ADR-018 put real
background work on Redis in Phase 10, and this does not pre-empt that: it has no
job types, no retries, no dead-letter handling and no fan-out. It wakes up, asks
whether the day's budget is unspent, and if so makes one fetch. When the queue
arrives this becomes a job definition and the loop below is deleted.

**Why it is safe to run in-process.** Every decision it makes is read from the
database, not from memory, so a container restart mid-day resumes where it left
off rather than starting the budget again. It holds no state between ticks.

**What it does not do.** It does not retry. On a free tier measured in hundreds
of requests a month, a retry spends a scarce unit to re-ask a question that just
failed, and on a quota error it makes matters worse (ADR-019).
"""

from __future__ import annotations

import asyncio

from app.core.config import Settings, get_settings
from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.integrations.jobs import get_job_provider
from app.repositories.job import CompanyRepository, JobRepository, JobSkillRepository
from app.repositories.job_fetch import JobFetchRunRepository
from app.repositories.skill import SkillRepository
from app.services.job.fetch import fetch_and_import
from app.services.job.rotation import build_queries, next_query
from app.services.job.service import JobService

log = get_logger(__name__)

#: How long to wait before the first tick, when that is sooner than the interval.
#:
#: It does not fetch on startup. A crash loop or a dev reload would then turn
#: every restart into a request, and quota does not come back. But waiting a
#: full interval is too long the other way: with `--reload` the process restarts
#: on every edit, so an hour's wait means it never fetches at all on a machine
#: someone is working on. Five minutes is longer than any restart loop and
#: shorter than any working session. The budget in the database is what actually
#: caps spending — this only decides when the first check happens.
FIRST_TICK_SECONDS = 300


async def run_one_fetch(settings: Settings) -> bool:
    """One tick. Returns whether a request was actually spent.

    Everything that decides *whether* to fetch is read fresh from the database,
    so two processes running this would at worst duplicate one request rather
    than run away with the budget. There is one process today; the comment is
    here because that is the assumption to check before adding a second.
    """
    provider = get_job_provider()
    if provider is None:
        return False

    async with get_session_factory()() as session:
        runs = JobFetchRunRepository(session)

        spent = await runs.requests_today()
        if spent >= settings.jobs_auto_fetch_per_day:
            return False

        queries = build_queries()
        last_used = await runs.last_used()
        query = next_query(queries, last_used)
        if query is None:
            return False

        exhausted = len(last_used) >= len(queries)
        if exhausted and spent >= settings.jobs_auto_fetch_exhausted_per_day:
            # Every question has been asked at least once. Re-asking the oldest
            # picks up whatever the index has added since, which the measurements
            # in rotation.py suggest is little — so it drops to a trickle rather
            # than spending a full day's budget on mostly-duplicates.
            return False

        service = JobService(
            jobs=JobRepository(session),
            companies=CompanyRepository(session),
            job_skills=JobSkillRepository(session),
            skills=SkillRepository(session),
        )
        result = await fetch_and_import(
            provider=provider,
            service=service,
            query=query,
            country=settings.jobs_fetch_country,
            max_pages=1,
        )

        await runs.record(
            query=query,
            country=settings.jobs_fetch_country,
            # What was asked for, not what came back: a page that timed out
            # still counted against the quota.
            requests_spent=max(result.pages_fetched, 1),
            created=result.created,
            duplicates=result.duplicates,
            failed=len(result.failed),
            quota_remaining=result.quota_remaining,
            scheduled=True,
            stop_reason=result.stop_reason,
        )
        await session.commit()

        log.info(
            "scheduled job fetch",
            query=query,
            created=result.created,
            duplicates=result.duplicates,
            failed=len(result.failed),
            quota_remaining=result.quota_remaining,
            spent_today=spent + 1,
            budget=settings.jobs_auto_fetch_per_day,
            queries_used=len(last_used),
            queries_total=len(queries),
            stop_reason=result.stop_reason,
        )
        return True


async def scheduler_loop() -> None:
    """Wake periodically and fetch if the day's budget allows.

    A poll rather than "run at 09:00": the process is not always up, and a fixed
    time missed while the machine was off would simply be skipped. Checking the
    budget on a timer means a day's allowance is spent whenever the app happens
    to be running, which on a laptop is the only schedule that actually holds.
    """
    settings = get_settings()
    interval = settings.jobs_auto_fetch_interval_minutes * 60

    log.info(
        "job fetch scheduler started",
        per_day=settings.jobs_auto_fetch_per_day,
        interval_minutes=settings.jobs_auto_fetch_interval_minutes,
    )

    delay = min(interval, FIRST_TICK_SECONDS)
    while True:
        # Sleep first, always: fetching the instant the process starts would
        # turn a crash loop into a burst of requests.
        await asyncio.sleep(delay)
        delay = interval
        try:
            await run_one_fetch(settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never let one bad tick kill the loop — the next one may well
            # succeed, and a scheduler that dies silently is worse than one
            # that logs and carries on.
            log.exception("scheduled job fetch failed")


def start(settings: Settings) -> asyncio.Task[None] | None:
    """Start the loop if it is switched on. Returns the task so it can be cancelled."""
    if not settings.jobs_auto_fetch_enabled:
        return None
    if get_job_provider() is None:
        log.warning("auto fetch is enabled but no jobs provider is configured — not starting")
        return None
    return asyncio.create_task(scheduler_loop(), name="job-fetch-scheduler")
