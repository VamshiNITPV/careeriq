"""Moving one application along the funnel, and recording that it moved (US-7.1).

`lifecycle.py` next door says which moves are *allowed* and knows nothing about
rows. This is the part that needs a database: it applies an allowed move, keeps
the two CHECK constraints on `applications` satisfied, and appends the event
that AC2 requires.

## Why the event is written here and not by a trigger

The log is the only record of *where* an application stopped — `status` alone
cannot distinguish a rejection after four interviews from one the week it was
sent, and those are different outcomes to the person looking at their own
results. US-7.2's analytics read from it. Writing it beside the status change,
in the same transaction, is what makes "every transition writes an event" a fact
rather than an intention: there is no path that changes one without the other.

## The two constraints this has to respect

`applications` carries checks that the funnel can violate, and both are load
bearing rather than tidiness:

- **`applied_has_timestamp`** — `applied_at` is NULL when SAVED, set for every
  active stage past it, and unconstrained once REJECTED or WITHDRAWN. So moving
  forward out of SAVED has to fill it, and moving back to SAVED has to clear it,
  or the write fails at the database.
- **`saved_or_applied`** — `is_saved OR status <> 'SAVED'`. A row that is
  neither bookmarked nor applied to has nothing left to say, so it is deleted
  rather than kept. This makes one move genuinely impossible, and it is refused
  rather than worked around; see `NothingLeftError`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.models.application import Application, ApplicationEvent
from app.models.enums import ApplicationEventType, ApplicationStatus
from app.services.application import lifecycle


class NothingLeftError(ValueError):
    """Moving back to SAVED would leave a row that means nothing.

    Reachable only from an application that was marked applied without ever
    being bookmarked. Sending it back to SAVED would say "not applied, not
    saved", which `saved_or_applied` forbids and which has no meaning anyway —
    there would be nothing left to find the job by.

    **Refused rather than fixed by setting `is_saved`.** Quietly bookmarking a
    job because the user corrected a status is precisely the bug
    `ApplicationStatusUpdate` was split in two to end: recording one fact must
    never rewrite the other. The caller is told to delete instead, which is what
    "I did not apply and do not want this" actually means.
    """

    def __init__(self) -> None:
        super().__init__(
            "This job was marked applied but never saved, so moving it back to "
            "saved would leave no record of it at all. Delete the application "
            "instead, or bookmark the job first."
        )


def apply_transition(
    session: AsyncSession,
    application: Application,
    *,
    target: ApplicationStatus,
    occurred_at: datetime | None = None,
) -> ApplicationEvent:
    """Move `application` to `target`, appending the event that records it.

    Raises `lifecycle.IllegalTransitionError` if the funnel disallows the move,
    and `NothingLeftError` for the one allowed move that the row constraints
    make impossible. Neither mutates anything: the checks come first, so a
    refused transition leaves the application exactly as it was.

    Does not commit. The caller owns the transaction, like every other
    repository and service here — so the status change and its event land
    together or not at all.
    """
    current = application.status
    lifecycle.check(current, target)

    if target is ApplicationStatus.SAVED and not application.is_saved:
        raise NothingLeftError

    when = occurred_at or datetime.now(UTC)

    # Keep `applied_at` consistent with the stage before the status moves, so the
    # row never exists in a state `applied_has_timestamp` would reject.
    if target is ApplicationStatus.SAVED:
        application.applied_at = None
    elif target in lifecycle.ACTIVE and application.applied_at is None:
        # Entering APPLIED or beyond from SAVED. The timestamp is the moment the
        # user reports, not now: they are telling us when they applied, and
        # US-7.0 AC2 is that the system never infers this — recording their
        # answer is not inferring, overwriting it with the clock would be.
        application.applied_at = when

    application.status = target
    event = ApplicationEvent(
        id=uuid7(),
        application_id=application.id,
        from_status=current,
        to_status=target,
        event_type=ApplicationEventType.STATUS_CHANGE,
        occurred_at=when,
    )
    session.add(event)
    # Returned as well as added so the caller can log or surface it without
    # re-reading. The same object, not a copy — two would mean the row the caller
    # inspects is not the row that gets written.
    return event
