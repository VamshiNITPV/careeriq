"""Skill taxonomy and candidate skills (database.md section 3.2).

The taxonomy is the reason matching works at all: a candidate's "Postgres" and a
job's "PostgreSQL" have to resolve to the same identity before any scoring can
compare them. Aliases do that resolution once, so every downstream comparison is
between ids rather than between strings.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ProficiencyLevel


def _pg_enum(enum_cls: type, name: str) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        native_enum=True,
        create_type=False,
    )


class Skill(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "skills"

    # Canonical display form, e.g. "PostgreSQL".
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    # Lookup key: lowercased and punctuation-normalised, e.g. "postgresql".
    normalized_name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)

    category: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # {"postgres", "psql", "pg"} — normalised forms only. This is what makes a
    # resume saying "Postgres" match a job asking for "PostgreSQL".
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )

    # React implies JavaScript. Used later to credit partial matches rather than
    # scoring a React developer as having no JavaScript (ml.md section 4.1).
    parent_skill_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("skills.id", ondelete="SET NULL"), nullable=True
    )

    # Fraction of active jobs requiring it. Populated in Phase 5; drives gap
    # severity so priorities come from the corpus rather than from opinion.
    demand_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    # False for skills auto-created by extraction, true once a human confirms
    # them. Keeps the taxonomy from silently filling with parser noise.
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    __table_args__ = (
        # Trigram index for fuzzy lookup of near-miss spellings.
        Index(
            "ix_skills_trgm",
            "normalized_name",
            postgresql_using="gin",
            postgresql_ops={"normalized_name": "gin_trgm_ops"},
        ),
        # GIN over the array so alias containment is an index lookup.
        Index("ix_skills_aliases", "aliases", postgresql_using="gin"),
        Index("ix_skills_category", "category"),
        CheckConstraint(
            "demand_score IS NULL OR (demand_score >= 0 AND demand_score <= 1)",
            name="demand_score_is_fraction",
        ),
    )


class CandidateSkill(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "candidate_skills"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # RESTRICT: a skill referenced by a candidate is not deletable. Cascading
    # would silently erase part of someone's profile to tidy the taxonomy.
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("skills.id", ondelete="RESTRICT"), nullable=False
    )

    proficiency: Mapped[ProficiencyLevel | None] = mapped_column(
        _pg_enum(ProficiencyLevel, "proficiency_level"), nullable=True
    )
    years_of_experience: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)

    # Which upload produced this row. Provenance matters when a user asks why a
    # skill they never claimed is on their profile.
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("resume_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)

    # The idempotency rule for re-parsing (US-2.4 AC2): a re-parse may update
    # rows where this is false and must never overwrite one where it is true.
    # Without it, re-processing a resume would silently undo the user's
    # corrections.
    is_user_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    last_used_year: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    skill: Mapped[Skill] = relationship(lazy="joined")

    __table_args__ = (
        Index("ux_candidate_skills", "user_id", "skill_id", unique=True),
        Index("ix_candidate_skills_user", "user_id"),
        CheckConstraint(
            "extraction_confidence IS NULL "
            "OR (extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="confidence_is_fraction",
        ),
        CheckConstraint(
            "years_of_experience IS NULL OR years_of_experience >= 0",
            name="years_non_negative",
        ),
    )
