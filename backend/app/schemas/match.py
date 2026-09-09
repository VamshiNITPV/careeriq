"""The match score response (api.md section 2.4, US-4.1 and US-4.2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import SkillRequirement
from app.services.matching.weights import Dimension, DimensionStatus


class MatchDimension(BaseModel):
    """One line of the breakdown.

    `contribution` is `score x weight x 100`, rounded to one place. The six of
    them sum to `overall_score` **exactly** — that is US-4.1 AC2, and it is what
    makes the score reproducible by hand from this payload rather than something
    the user has to take on trust.
    """

    dimension: Dimension
    score: Decimal
    weight: Decimal
    contribution: Decimal
    #: Beyond api.md's original contract, and the reason the rest of it stays
    #: honest. A dimension we could not compute scores a neutral 0.5, and
    #: without this the interface could not tell that apart from a genuine
    #: middling result — it would draw a half-full bar for a measurement that
    #: never happened.
    #:
    #:   SCORED         both sides had data; the formula ran
    #:   NOT_STATED     the job stated no requirement, so ml.md's principled
    #:                  default applies. Not ignorance about the user
    #:   NEEDS_PROFILE  the candidate side is empty — the user can fix this
    #:   NEEDS_DATA     missing from the posting or the index — the user cannot,
    #:                  and must never be shown a call to action for it
    status: DimensionStatus
    reason: str


class MatchedSkill(BaseModel):
    id: uuid.UUID
    name: str
    requirement: SkillRequirement


class MatchSkills(BaseModel):
    """The skills behind the skill dimension (US-4.2).

    `partial` holds taxonomy matches — the job asks for React and the candidate
    listed JavaScript, or the reverse. api.md's example shows a second kind of
    partial, an exact match with insufficient years; that one cannot occur yet,
    because `candidate_skills.years_of_experience` is populated on no row in the
    database.
    """

    matched: list[MatchedSkill] = Field(default_factory=list)
    partial: list[MatchedSkill] = Field(default_factory=list)
    missing: list[MatchedSkill] = Field(default_factory=list)


class MatchResponse(BaseModel):
    """How one caller matches one job.

    Always `200`, with `availability` saying what kind of answer this is — the
    same shape `/jobs/{id}/similar` established, and for the same reason. An
    error status would be wrong: nothing failed.

      READY      all six dimensions ran
      PARTIAL    computed, but the semantic dimension could not run — no
                 provider configured, or one of the two vectors is not built
                 yet. The full breakdown still returns and still sums.
                 **The common case today**
      NO_RESUME  this caller has uploaded nothing. `overall_score` is null and
                 `breakdown` is empty, because showing "20 / 100" to someone we
                 know nothing about is not a low score, it is a fabricated
                 judgement
    """

    job_id: uuid.UUID
    availability: Literal["READY", "PARTIAL", "NO_RESUME"]
    overall_score: Decimal | None = None
    #: Always the six, in documented weight order, never sorted by score. Fixed
    #: order is what makes two payloads diffable and what turns the by-hand
    #: check into a straight read down one column.
    breakdown: list[MatchDimension] = Field(default_factory=list)
    #: The share of the formula that actually measured something about this
    #: person — the sum of the `SCORED` rows' weights. Today it is typically
    #: 0.60, and the interface says so out loud rather than presenting a number
    #: that four neutral dimensions helped produce as if it were fully informed.
    scored_weight: Decimal = Decimal("0")
    skills: MatchSkills = Field(default_factory=MatchSkills)
    #: Which weight set produced this (ADR-005). A learned ranker will write
    #: under a different one, so a stored score stays interpretable.
    ranking_version: str | None = None
    #: Which resume version the score was computed against. A real input, not
    #: only provenance: `candidate_embeddings` is keyed on the version, so the
    #: semantic dimension compares that version's vector and a different one can
    #: score the same job differently.
    resume_version_id: uuid.UUID | None = None
    computed_at: datetime | None = None
