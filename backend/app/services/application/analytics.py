"""What the funnel says happened (US-7.2).

## Rates come from the event log, not from `applications.status`

This is the whole reason `application_events` exists, and getting it wrong would
make every number here quietly too low. An application sitting at REJECTED today
may have been rejected *after* two interviews, and counting only current status
would score it as never having reached one. "Did this reach an interview" is a
question about history, and the current row does not hold history.

So a stage counts as reached when **an event recorded arriving there**, or when
the application is sitting there now. The second half covers rows that never
passed through the transition endpoint — `PUT /jobs/{id}/application` creates an
application at APPLIED without writing an event, and a seed may insert any
status directly.

## What counts as an application

`applied_at IS NOT NULL`, which the `applied_has_timestamp` CHECK makes exactly
"this left the SAVED stage at some point". A bookmark is not an application, and
counting one would dilute every rate below with jobs the user never sent
anything to.

Note this correctly keeps applications that were later rejected or withdrawn:
they were still sent, and dropping them would compute a success rate over only
the successes.

## Small segments get a label, not a number

A segment of two applications with one interview is not a 50% interview rate; it
is two applications. `MIN_FOR_RATE` is the line, from US-7.2 AC3, and below it
the counts are still reported — those are facts — while the rates come back
`None`. Returning the number *and* a warning flag was the alternative and is
weaker: a number on screen gets read, and a caveat beside it does not undo that.

This is the same refusal the near-duplicate detector makes at 0.750 precision
and the skill-gap screen makes with NO_TARGET — say what is known, decline to
imply what is not.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, case, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application, ApplicationEvent
from app.models.enums import ApplicationStatus
from app.models.job import Job

#: Below this many applications a segment reports counts only (AC3).
#:
#: Five is the acceptance criterion's number rather than a derived one. It is
#: low for statistical comfort — a 1-in-5 rate still has a wide interval — but
#: the alternative for a personal job hunt is reporting nothing for months.
MIN_FOR_RATE = 5

#: Shown for a posting that never carried the field. Grouping several of those
#: under one heading beats dropping them, which would make the segment counts
#: disagree with the total and look like a bug.
UNKNOWN = "Not stated"


@dataclass(frozen=True, slots=True)
class Segment:
    """One slice of the funnel, and how much to trust it."""

    label: str
    applications: int
    interviews: int
    offers: int

    @property
    def low_confidence(self) -> bool:
        return self.applications < MIN_FOR_RATE

    @property
    def interview_rate(self) -> float | None:
        return None if self.low_confidence else self.interviews / self.applications

    @property
    def offer_rate(self) -> float | None:
        return None if self.low_confidence else self.offers / self.applications


@dataclass(frozen=True, slots=True)
class FunnelReport:
    overall: Segment
    by_role: list[Segment]
    by_location: list[Segment]


def _reached(status: ApplicationStatus) -> Select[tuple[bool]]:
    """Whether this application ever arrived at `status`.

    Two ways, because there are two ways a status is set. The event log is the
    real answer and covers an application that has since moved on; the current
    status covers rows written without an event, which `PUT
    /jobs/{id}/application` and the demo seed both do.
    """
    return or_(
        exists().where(
            ApplicationEvent.application_id == Application.id,
            ApplicationEvent.to_status == status,
        ),
        Application.status == status,
    )


@dataclass(frozen=True, slots=True)
class _Row:
    """One application, reduced to what the tallies need."""

    #: Lowercased, so case variants of one job title group together.
    role_key: str
    #: The posting's own title, for showing. `normalized_title` is lowercase —
    #: correct as a grouping key and wrong on screen, where "backend engineer"
    #: reads as a bug rather than as a heading.
    role_label: str
    location: str
    interviewed: bool
    offered: bool


def _tally(rows: list[_Row], key: str, label: str) -> list[Segment]:
    """Group by one attribute, label by another.

    The two are separate because grouping wants a normalised value and a reader
    wants the original. For location they are the same attribute; for role they
    are not.
    """
    buckets: dict[str, list[_Row]] = {}
    for row in rows:
        buckets.setdefault(getattr(row, key), []).append(row)

    segments = [
        Segment(
            # The first row's label stands for the group. They differ only by
            # case within a bucket, so any of them is as good as another.
            label=getattr(entries[0], label),
            applications=len(entries),
            interviews=sum(1 for row in entries if row.interviewed),
            offers=sum(1 for row in entries if row.offered),
        )
        for entries in buckets.values()
    ]
    # Busiest first, then alphabetically so the order is stable between calls
    # rather than following whatever the dict happened to hold.
    segments.sort(key=lambda s: (-s.applications, s.label))
    return segments


async def funnel_report(session: AsyncSession, *, user_id: uuid.UUID) -> FunnelReport:
    """Count what happened to this user's applications.

    One query, grouped in Python. The set is one person's applications — tens,
    bounded by how many jobs somebody applies to — which is the same reasoning
    `list_for_user` gives for not paginating. Pivoting this in SQL would be
    denser to read and no faster at this size.
    """
    rows = (
        await session.execute(
            select(
                # Both: `normalized_title` is the column database.md marks as
                # the analytics grouping key, and it is lowercased — so the raw
                # title comes too, to be what a reader actually sees.
                Job.normalized_title.label("role_key"),
                Job.title.label("title"),
                Job.location.label("location"),
                case((_reached(ApplicationStatus.INTERVIEW), True), else_=False).label(
                    "interviewed"
                ),
                case((_reached(ApplicationStatus.OFFER), True), else_=False).label("offered"),
            )
            .select_from(Application)
            .join(Job, Job.id == Application.job_id)
            .where(
                Application.user_id == user_id,
                Application.deleted_at.is_(None),
                # "Was actually sent." A bookmark is not an application.
                Application.applied_at.is_not(None),
            )
        )
    ).all()

    parsed = [
        _Row(
            role_key=(row.role_key or row.title or "").strip().lower() or UNKNOWN,
            role_label=(row.title or "").strip() or UNKNOWN,
            location=(row.location or "").strip() or UNKNOWN,
            interviewed=row.interviewed,
            offered=row.offered,
        )
        for row in rows
    ]

    return FunnelReport(
        overall=Segment(
            label="All applications",
            applications=len(parsed),
            interviews=sum(1 for row in parsed if row.interviewed),
            offers=sum(1 for row in parsed if row.offered),
        ),
        by_role=_tally(parsed, "role_key", "role_label"),
        by_location=_tally(parsed, "location", "location"),
    )
