"""Resume request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ProcessingStatus, ProficiencyLevel


class ResumeVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    original_filename: str
    mime_type: str
    file_size_bytes: int
    processing_status: ProcessingStatus
    processing_error: str | None
    processed_at: datetime | None
    created_at: datetime

    # Deliberately absent: storage_key and content_hash. The key is an internal
    # address, and exposing it invites clients to construct their own.


class ResumeVersionDetail(ResumeVersionSummary):
    raw_text: str | None
    parsed_sections: dict[str, Any] | None
    parsed_entities: dict[str, Any] | None


class ResumeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    is_primary: bool
    current_version_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ResumeDetail(ResumeRead):
    versions: list[ResumeVersionSummary]


class ResumeUploadResponse(BaseModel):
    """202 Accepted payload (api.md section 2.3).

    Carries what the client needs to follow the work: the version to poll and
    the channel it will use once WebSockets land in Phase 10.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "resume_id": "01a0619b-d407-7b75-a46b-2c57c96e9855",
                "version_id": "01a0619b-d407-7b75-a46b-2c57c96e9856",
                "status": "PENDING",
                "is_duplicate": False,
                "poll_url": "/api/v1/resumes/versions/01a0619b-.../status",
            }
        }
    )

    resume_id: uuid.UUID
    version_id: uuid.UUID
    status: ProcessingStatus
    is_duplicate: bool = Field(
        description="True when this file was already uploaded; the previous parse was reused."
    )
    poll_url: str


class ProcessingStatusResponse(BaseModel):
    """Progress for a version being parsed (US-2.2)."""

    version_id: uuid.UUID
    status: ProcessingStatus
    # Coarse percentage derived from the stage. Honest about being an estimate
    # rather than pretending to track bytes through the parser.
    percent: int
    stage_label: str
    error: str | None = None
    is_terminal: bool


class SuggestedSkill(BaseModel):
    """A skill the resume demonstrates but never names.

    Deliberately a distinct type from an extracted skill. These are the system's
    interpretation of the candidate's words, not something the candidate said,
    so they are never written to a profile and always travel with the sentence
    that produced them (ADR-012).
    """

    skill_id: uuid.UUID | None = Field(
        default=None,
        description="Null if the suggested skill is not in the taxonomy yet.",
    )
    name: str
    confidence: Decimal
    evidence: str = Field(description="The exact sentence this was inferred from.")
    section: str


class SuggestionsResponse(BaseModel):
    version_id: uuid.UUID
    suggestions: list[SuggestedSkill]
    unknown_terms: list[str] = Field(
        description="Terms found in the skills section that the taxonomy does not recognise."
    )


class ResumeUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    is_primary: bool | None = None


class SkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str | None


class CandidateSkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    skill: SkillRead
    proficiency: ProficiencyLevel | None
    years_of_experience: Decimal | None
    extraction_confidence: Decimal | None
    is_user_verified: bool
    last_used_year: int | None
    created_at: datetime


class CandidateSkillCreate(BaseModel):
    skill_id: uuid.UUID
    proficiency: ProficiencyLevel | None = None
    years_of_experience: Decimal | None = Field(default=None, ge=0, le=70)
    last_used_year: int | None = Field(default=None, ge=1950, le=2100)


class CandidateSkillUpdate(BaseModel):
    proficiency: ProficiencyLevel | None = None
    years_of_experience: Decimal | None = Field(default=None, ge=0, le=70)
    last_used_year: int | None = Field(default=None, ge=1950, le=2100)
