"""Fetch-run data access: the budget and the rotation state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models.job_fetch import JobFetchRun
from app.repositories.base import BaseRepository


class JobFetchRunRepository(BaseRepository[JobFetchRun]):
    model = JobFetchRun

    async def requests_since(self, since: datetime) -> int:
        """Provider requests spent since a moment. The budget check.

        Sums `requests_spent` rather than counting rows: one run can page more
        than once, and the quota counts pages.
        """
        return int(
            await self.session.scalar(
                select(func.coalesce(func.sum(JobFetchRun.requests_spent), 0)).where(
                    JobFetchRun.started_at >= since
                )
            )
            or 0
        )

    async def requests_today(self) -> int:
        """Spent since midnight UTC.

        UTC rather than a local day, because every other timestamp in the schema
        is UTC and a scheduler that changes its mind about when "today" started
        would double-spend twice a year.
        """
        now = datetime.now(UTC)
        return await self.requests_since(now.replace(hour=0, minute=0, second=0, microsecond=0))

    async def last_used(self, *, within_days: int = 90) -> dict[str, datetime]:
        """When each query was last asked.

        Bounded, so the rotation is not decided by a query tried once months
        ago — beyond that window a query is as good as unused, which is the
        honest reading when the index has had that long to change.
        """
        cutoff = datetime.now(UTC) - timedelta(days=within_days)
        rows = await self.session.execute(
            select(JobFetchRun.query, func.max(JobFetchRun.started_at))
            .where(JobFetchRun.started_at >= cutoff)
            .group_by(JobFetchRun.query)
        )
        return dict(rows.all())  # type: ignore[arg-type]  # (query, max(started_at)) pairs

    async def record(
        self,
        *,
        query: str,
        country: str,
        requests_spent: int,
        created: int,
        duplicates: int,
        failed: int,
        quota_remaining: int | None,
        scheduled: bool,
        stop_reason: str | None,
    ) -> JobFetchRun:
        """Write the run down.

        Called even when a fetch created nothing, and especially then: a run
        that spent a request and found only duplicates has to count against the
        budget, and a corpus that stops growing needs to show whether fetches
        stopped or merely stopped finding anything.
        """
        run = JobFetchRun(
            query=query,
            country=country,
            requests_spent=requests_spent,
            created=created,
            duplicates=duplicates,
            failed=failed,
            quota_remaining=quota_remaining,
            scheduled=scheduled,
            stop_reason=stop_reason,
        )
        self.add(run)
        await self.flush()
        return run
