"""Relevance feedback on recommendations (api.md section 2.5, ADR-005).

**Nothing reads this table, and that is deliberate.** ADR-005's migration path
to a learned ranker needs labelled relevance judgements, and those can only be
gathered forward in time — an endpoint added later starts from an empty table,
however good the model is by then. Collecting from day one is the cheap half of
that plan; the expensive half is the model.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import RecommendationFeedback


class RecommendationFeedbackRow(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "recommendation_feedback"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # CASCADE rather than SET NULL: a judgement about a posting that no longer
    # exists cannot be used as a training label, because the features it was
    # about are gone with it.
    job_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )

    rating: Mapped[RecommendationFeedback] = mapped_column(
        SAEnum(
            RecommendationFeedback,
            # `recommendation_rating`, not `recommendation_feedback`: creating a
            # table implicitly creates a composite type of the same name, so the
            # enum and the table it lives in cannot share one. PostgreSQL says so
            # only at CREATE TABLE time, with a HINT that is easy to skim past.
            name="recommendation_rating",
            values_callable=lambda e: [m.value for m in e],
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
    )

    #: Which weight set produced the ranking they were reacting to. Without it a
    #: label is uninterpretable later: "this was a bad recommendation" says
    #: nothing unless you know which ranker made it.
    ranking_version: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # One opinion per user per job, updated rather than appended. A history
        # of somebody changing their mind is not a training label, and the
        # upsert is what keeps the table one row per judgement.
        Index("ux_recommendation_feedback", "user_id", "job_id", unique=True),
        Index("ix_recommendation_feedback_job", "job_id"),
    )
