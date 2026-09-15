"""Resume optimization requests and responses (US-6.1, api.md section 2.7)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AnalysisStatus, SuggestionDecision


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_version_id: uuid.UUID
    job_id: uuid.UUID


class AnalyzeResponse(BaseModel):
    analysis_id: uuid.UUID
    status: AnalysisStatus
    #: Where to poll. The work happens after the response is sent.
    poll_url: str


class SuggestionRead(BaseModel):
    id: uuid.UUID
    position: int
    section: str
    original: str
    suggested: str
    rationale: str
    #: Source lines the model cited.
    #:
    #: Shown so a reviewer can check the rewrite against the resume. Evidence,
    #: never proof: nothing stops a model citing a line that does not support
    #: its claim, which is why the validator ignores these and re-reads the
    #: resume itself.
    grounded_in: list[str]
    decision: SuggestionDecision
    decided_at: datetime | None


class AnalysisRead(BaseModel):
    analysis_id: uuid.UUID
    resume_version_id: uuid.UUID
    job_id: uuid.UUID
    status: AnalysisStatus
    #: Present only when FAILED, and then always.
    error: str | None
    suggestions: list[SuggestionRead]
    #: How many were discarded for inventing something (ADR-012 step 4).
    #:
    #: Reported rather than hidden. A validator that silently rejected
    #: everything would otherwise be indistinguishable from a model that had
    #: nothing to say, and the difference matters to whoever is reading the
    #: empty list.
    rejected_by_validator: int
    #: How many the parser could not read. A different problem with a different
    #: fix, so it is not summed with the above.
    dropped_malformed: int
    completed_at: datetime | None


class DecideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_suggestion_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Suggestions to apply. Everything else in the analysis is marked rejected.",
    )


class ApplyResponse(BaseModel):
    #: The **new** version. The source version is never mutated (US-6.1 AC3).
    resume_version_id: uuid.UUID
    version_number: int
    applied: int
    rejected: int
    message: str
