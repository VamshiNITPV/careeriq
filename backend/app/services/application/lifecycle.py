"""Which application status may follow which (US-7.1 AC1).

Pure: no database, no session, no clock. The rules are a property of the funnel
rather than of a row, so they are exhaustively testable against the enum alone —
the same reasoning `services/skill/learning.py` uses for its ordering.

## The shape AC1 asks for

    SAVED -> APPLIED -> ASSESSMENT -> INTERVIEW -> OFFER

with REJECTED and WITHDRAWN reachable from any active state. Those two are where
an application stops.

## Moving backwards is allowed between active states

Not in AC1, and deliberate. People mis-tap, and an employer occasionally moves
someone back a stage. Refusing would leave the only recovery as deleting the
application and losing its history, which is worse than recording a correction.
The event log makes every move visible, so a correction is auditable rather than
hidden — that is the whole reason the log exists.

What is *not* allowed is inventing a stage the user never reported. Nothing here
advances a status on its own; every transition is something they told us.

## Reopening

REJECTED and WITHDRAWN are endings, not prisons. A rejection gets reversed and a
withdrawal gets reconsidered, and a mis-tap on either would otherwise strand the
row forever. Reopening returns to APPLIED rather than guessing a stage: the log
holds where it actually was, and a caller that wants to restore that can read it
— but the safe default is the one stage we know for certain it passed through.
"""

from __future__ import annotations

from app.models.enums import ApplicationStatus

#: The funnel, in order. Position matters only for describing progress; the
#: rules below do not depend on it.
FUNNEL: tuple[ApplicationStatus, ...] = (
    ApplicationStatus.SAVED,
    ApplicationStatus.APPLIED,
    ApplicationStatus.ASSESSMENT,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
)

#: Where an application stops.
TERMINAL: frozenset[ApplicationStatus] = frozenset(
    {ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}
)

ACTIVE: frozenset[ApplicationStatus] = frozenset(FUNNEL)

#: Where reopening a stopped application lands.
#:
#: APPLIED rather than SAVED: the application was submitted, and sending it back
#: to a bookmark would lose that. Not the stage it stopped at either, because
#: that is a guess this module has no evidence for -- the log does.
REOPEN_TO = ApplicationStatus.APPLIED


class IllegalTransitionError(ValueError):
    """The requested move is not one the funnel allows."""

    def __init__(self, current: ApplicationStatus, target: ApplicationStatus) -> None:
        super().__init__(f"An application cannot go from {current} to {target}.")
        self.current = current
        self.target = target


def allowed_from(current: ApplicationStatus) -> frozenset[ApplicationStatus]:
    """Every status reachable in one step from `current`.

    Excludes `current` itself: staying put is not a transition, and recording an
    event for it would put noise in a log whose value is that every row means
    something happened.
    """
    if current in TERMINAL:
        return frozenset({REOPEN_TO})
    return frozenset((ACTIVE | TERMINAL) - {current})


def check(current: ApplicationStatus, target: ApplicationStatus) -> None:
    """Raise unless `current -> target` is allowed."""
    if target not in allowed_from(current):
        raise IllegalTransitionError(current, target)


def is_terminal(status: ApplicationStatus) -> bool:
    return status in TERMINAL


def progress(status: ApplicationStatus) -> int | None:
    """How far along the funnel, or None for a stopped application.

    Used for ordering and for the funnel counts in US-7.2. None rather than a
    number for REJECTED and WITHDRAWN, because they are not a *position* -- an
    application rejected after an interview and one rejected after applying
    stopped at different depths, and the log is what knows which.
    """
    return FUNNEL.index(status) if status in ACTIVE else None
