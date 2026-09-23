"""The funnel's numbers (US-7.2)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FunnelSegment(BaseModel):
    """One slice of the funnel.

    Counts are always present — they are facts. **The rates are `None` below
    five applications** (AC3), and `low_confidence` says why. That is not the
    same as a rate of zero, and a client must not render it as one: no rate
    means "not enough happened to say", and 0.0 means "five or more, none of
    them reached it".
    """

    label: str
    applications: int
    interviews: int
    offers: int

    #: Fraction, not a percentage. Formatting is the client's decision, and
    #: rounding here would bake one reader's precision into everybody's answer.
    interview_rate: float | None = Field(default=None, ge=0, le=1)
    offer_rate: float | None = Field(default=None, ge=0, le=1)

    #: True when `applications` is under five, so the rates above are null.
    low_confidence: bool


class FunnelAnalyticsResponse(BaseModel):
    """Application counts and outcome rates, whole and sliced (US-7.2).

    **Computed per request, never stored**, for the reason ADR-006 gives for not
    caching match scores: every number here is derived from rows that change,
    and a stored copy would be wrong more often than right.

    All four of AC2's slices. Role and location come from the posting; resume
    version and score band come from a snapshot taken when the application was
    sent, because neither is recoverable afterwards — a resume gets edited and
    the corpus moves, so recomputing would answer "how well would this match
    today" rather than the question the funnel asks.

    Applications sent before that snapshot existed carry neither, and appear in
    the last two lists under a single "Not recorded" heading rather than being
    dropped. Dropping them would make the segments disagree with the headline
    count, which reads as a bug; naming them reads as the truth.
    """

    overall: FunnelSegment
    by_role: list[FunnelSegment]
    by_location: list[FunnelSegment]
    by_resume: list[FunnelSegment]
    by_score_band: list[FunnelSegment]

    #: The threshold AC3 sets, sent so a client can explain itself without
    #: hard-coding a number that then drifts from the server's.
    min_for_rate: int

    segments_available: list[str]
