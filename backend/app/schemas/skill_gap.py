"""Skill gap responses (US-5.1)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel

from app.services.skill.gaps import GapSeverity, GapStatus


class SkillGapRead(BaseModel):
    skill_id: uuid.UUID
    name: str
    category: str
    status: GapStatus
    severity: GapSeverity
    #: Weighted share of the target jobs asking for this, in [0, 1].
    #:
    #: A Decimal rather than a float, like every other fraction in this API: a
    #: float renders 0.35 as 0.35000000000000003 in some clients.
    frequency: Decimal
    job_count: int


class SkillGapsResponse(BaseModel):
    """The gaps, and what they were computed against.

    `target_jobs` is not decoration. A report built from four postings is a
    different claim from one built from ninety, and a reader who cannot see the
    denominator will over-read a small sample. The interface shows it.
    """

    items: list[SkillGapRead]
    target_jobs: int
    target_roles: list[str]
    job_id: uuid.UUID | None = None
    #: Why `items` may be empty, so the three causes are distinguishable.
    #:
    #: NO_TARGET   the user has set no target roles
    #: NO_JOBS     roles are set, but no live posting matches them
    #: READY       the computation ran
    availability: str = "READY"
