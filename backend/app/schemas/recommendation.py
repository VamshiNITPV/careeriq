"""Recommendation request and response schemas (api.md section 2.5)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import RecommendationFeedback
from app.schemas.job import JobSummary
from app.schemas.match import MatchDimension, MatchSkills


class RecommendedJob(BaseModel):
    """One ranked posting.

    Carries the full `JobSummary` for the same reason `/similar` does: the card
    on screen is the ordinary browse card, so the bookmark, the tags, the
    posting age and this caller's saved/applied state all come for free rather
    than needing a second request per row.

    The breakdown rides along rather than being fetched per card. It is already
    computed — the ranking cannot exist without it — and a list of twenty jobs
    that each needed a follow-up request to explain itself would make the
    explanation the thing users never see.
    """

    job: JobSummary
    score: Decimal
    breakdown: list[MatchDimension]
    scored_weight: Decimal
    skills: MatchSkills


class RecommendationsResponse(BaseModel):
    """Ranked jobs for the caller.

    `availability` rather than an error status, the discriminator `/similar` and
    `/match` both use. An empty `items` has three meanings and the interface has
    to say which:

      READY      the ranking ran
      PENDING    this caller's resume has no vector yet, so there was nothing to
                 compare against. Not a failure — the indexer simply has not
                 reached them — and not something a spinner should imply is
                 seconds away
      NO_RESUME  nothing uploaded at all. The remedy is a different one, and it
                 is the user's to take
    """

    items: list[RecommendedJob] = Field(default_factory=list)
    availability: Literal["READY", "PENDING", "NO_RESUME"]
    #: Opaque. Absent on the last page — a cursor that is always present makes a
    #: client fetch an empty response to discover it has finished.
    next_cursor: str | None = None
    limit: int
    #: How many of the recalled set survived the filters, for the caller's own
    #: sanity rather than for display. Deliberately **not** a corpus-wide total:
    #: two-stage retrieval never looks at the whole corpus, so any "total" would
    #: be a number about the recall set dressed up as a number about the market.
    considered: int = 0
    ranking_version: str | None = None
    resume_version_id: uuid.UUID | None = None
    computed_at: datetime | None = None


class FeedbackRequest(BaseModel):
    """What the user thought of one recommendation (api.md section 2.5).

    `NOT_RELEVANT` and `NOT_INTERESTED` are distinct on purpose. The first says
    the score was wrong; the second can sit on a perfectly scored job the user
    simply does not want. Collapsing them would teach a future ranker that a
    correct prediction was a mistake — which is worse than collecting nothing.
    """

    rating: RecommendationFeedback
