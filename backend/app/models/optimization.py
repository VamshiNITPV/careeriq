"""Resume optimization runs and the suggestions they produce (US-6.1).

`database.md` does not specify these tables; they are designed here from the API
contract in `api.md` section 2.7 and from what ADR-012 requires to be auditable.

## Why suggestions are stored at all

The learning path is derived on every request because it is a view of data that
moves. A suggestion is the opposite: it is **a specific thing a model said at a
specific time**, and the user's accept or reject is a decision about that exact
text. Regenerating would produce different words, so a stored decision would
point at nothing.

It is also the audit trail ADR-012 needs. If a fabricated claim ever reaches a
resume, the question is which suggestion carried it, what the model was asked,
and what the validator thought -- and none of that is answerable from a row that
was thrown away.

## Rejected suggestions stay

A rejected row is evidence the user was shown something and said no, which is
different from never having been offered it. It also stops the feature
re-proposing what has already been refused.

## Nothing here mutates a resume

Accepting a suggestion creates a **new** `resume_versions` row (US-6.1 AC3); the
source version is immutable and these tables only ever reference it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AnalysisStatus, SuggestionDecision


def _pg_enum(enum_cls: type, name: str) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        native_enum=True,
        create_type=False,
    )


class OptimizationAnalysis(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One run of "tailor this resume version to this job"."""

    __tablename__ = "optimization_analyses"
    __table_args__ = (
        # A count is a count. Negative means the writer miscounted, and saying
        # so at the moment it happens beats a nonsense number in a report weeks
        # later.
        CheckConstraint("rejected_by_validator >= 0", name="ck_analyses_rejected_non_negative"),
        CheckConstraint("dropped_malformed >= 0", name="ck_analyses_dropped_non_negative"),
        # FAILED must explain itself, like ProcessingStatus.
        CheckConstraint(
            "status <> 'FAILED' OR error IS NOT NULL", name="ck_analyses_failed_has_reason"
        ),
        # The listing query: this user's analyses, newest first.
        Index("ix_optimization_analyses_user_created", "user_id", text("created_at DESC")),
        # Not automatic on a foreign key, and RESTRICT makes every DELETE on
        # resume_versions and jobs check this table.
        Index("ix_optimization_analyses_resume_version", "resume_version_id"),
        Index("ix_optimization_analyses_job", "job_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # RESTRICT, not CASCADE. The version is the ground truth every suggestion was
    # validated against, so deleting it would leave rows claiming to be grounded
    # in a document that no longer exists.
    resume_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("resume_versions.id", ondelete="RESTRICT"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )

    status: Mapped[AnalysisStatus] = mapped_column(
        _pg_enum(AnalysisStatus, "analysis_status"),
        nullable=False,
        default=AnalysisStatus.PENDING,
        server_default=AnalysisStatus.PENDING.value,
    )
    #: Why it failed, in words a user can read. Always set when FAILED.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: How many suggestions the validator threw away (ADR-012 step 4).
    #:
    #: Stored rather than derived, because rejected suggestions are **not** kept:
    #: returning one to the user is the exact thing the validator exists to
    #: prevent, and a row that is never shown is a row waiting to be shown by
    #: mistake. The count is what keeps the behaviour observable -- without it,
    #: a validator that silently rejected everything would look like a model
    #: that had nothing to say.
    rejected_by_validator: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    #: Entries dropped for being malformed, separately from fabrication.
    #:
    #: A different problem with a different fix: one is a model inventing facts,
    #: the other is a model returning the wrong shape. Summing them would hide
    #: which.
    dropped_malformed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    #: Which prompt produced this, e.g. "resume_optimization@1".
    #:
    #: The reason ml.md versions prompts at all. Without it, "suggestions got
    #: worse last week" is unanswerable.
    prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The model that answered, as the provider reported it -- not as configured.
    #: An alias can move underneath a pinned name.
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OptimizationSuggestion(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """One proposed rewrite that survived validation.

    No `updated_at`: the text is what the model said and never changes. The
    user's decision does, and it carries its own timestamp -- keeping them apart
    means "when was this suggested" and "when was it acted on" stay separate
    facts.
    """

    __tablename__ = "optimization_suggestions"
    __table_args__ = (
        # A rewrite identical to its source is not a suggestion; it asks a
        # reviewer to decide between two identical things. The parser drops
        # these, and this stops any other writer creating one.
        CheckConstraint("original <> suggested", name="ck_suggestions_actually_differ"),
        # A decision that is not PENDING happened at a time. Without this an
        # accepted suggestion with no timestamp is indistinguishable from a
        # write that half-completed.
        CheckConstraint(
            "decision = 'PENDING' OR decided_at IS NOT NULL",
            name="ck_suggestions_decided_has_time",
        ),
        # Only an accepted suggestion can have produced a version.
        CheckConstraint(
            "applied_version_id IS NULL OR decision = 'ACCEPTED'",
            name="ck_suggestions_applied_was_accepted",
        ),
        # The read path: one analysis's suggestions in presentation order.
        Index("ix_optimization_suggestions_analysis_position", "analysis_id", "position"),
        Index("ix_optimization_suggestions_applied_version", "applied_version_id"),
    )

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("optimization_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Order as presented, so a re-read shows the same list in the same order.
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Which part of the resume this belongs to, e.g. "experience". Free text
    #: rather than an enum: it comes from a model and an unexpected value should
    #: be shown, not refused.
    section: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    #: The resume text being replaced, copied exactly.
    original: Mapped[str] = mapped_column(Text, nullable=False)
    suggested: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))

    #: Source spans the model cited (api.md section 2.7).
    #:
    #: Evidence for a reviewer, never a safety mechanism: nothing stops a model
    #: citing a line that does not support its claim, which is why the validator
    #: ignores these and re-reads the resume itself.
    grounded_in: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    decision: Mapped[SuggestionDecision] = mapped_column(
        _pg_enum(SuggestionDecision, "suggestion_decision"),
        nullable=False,
        default=SuggestionDecision.PENDING,
        server_default=SuggestionDecision.PENDING.value,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: The version created when this was applied, if it was.
    #:
    #: SET NULL rather than CASCADE: deleting a produced version must not erase
    #: the record that the user accepted this suggestion.
    applied_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("resume_versions.id", ondelete="SET NULL"), nullable=True
    )

    #: What the validator found, kept even though it passed.
    #:
    #: A pass is a claim about safety, and a claim with no evidence behind it
    #: cannot be checked later. Shape: {"passed": true, "fabricated_entities": []}.
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
