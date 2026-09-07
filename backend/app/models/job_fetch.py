"""A record of every fetch from a jobs provider.

Three jobs, which is why it is a table rather than a counter in memory:

1. **The budget.** The provider allows a few hundred requests a month, so the
   scheduler has to know what it has already spent today. Held in memory, that
   count resets on every container restart and every code reload — and the
   scheduler would then fetch again, burning quota that cannot be recovered.
2. **The rotation.** Asking the same question twice returns the same jobs; the
   only thing that yields new ones is asking a question not asked before. This
   records which have been used and when, so the scheduler can pick the one
   left longest.
3. **The audit.** When the corpus stops growing, this says whether the fetches
   stopped, or ran and found nothing — two very different problems.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class JobFetchRun(Base, UUIDPrimaryKeyMixin):
    """One call to `fetch_and_import`, scheduled or manual.

    Append-only, so `CreatedAtMixin`'s reasoning applies — but the timestamp is
    named `started_at` rather than `created_at` because what matters is when the
    provider was asked, not when the row was written.
    """

    __tablename__ = "job_fetch_runs"

    query: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: Pages fetched — one provider request each, and the unit the quota counts.
    #: A request that times out or fails still spent one, so this is incremented
    #: from what the provider was actually asked, not from what came back.
    requests_spent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: As the provider last reported it. Null when it publishes no such header.
    quota_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: False for an admin pressing the button. A boolean rather than an enum:
    #: this is an operational log with exactly two origins, and a native type
    #: would be a migration's worth of friction for no validation worth having.
    scheduled: Mapped[bool] = mapped_column(nullable=False, default=False)
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # "What have I spent today?" — the question the scheduler asks before
        # every run.
        Index("ix_job_fetch_runs_started_at", "started_at"),
        # "Which query has been left longest?" — the rotation's whole mechanism.
        Index("ix_job_fetch_runs_query", "query", "started_at"),
        CheckConstraint("requests_spent >= 0", name="requests_spent_not_negative"),
    )
