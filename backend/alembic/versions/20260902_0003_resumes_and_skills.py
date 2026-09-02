"""Add resumes, resume versions, and the skill taxonomy

Revision ID: 0003_resumes_and_skills
Revises: 0002_verification_tokens
Created: 2026-09-02

Check constraints use bare names — the metadata naming convention prepends
ck_<table>_ to whatever is supplied (see 0001 for the drift a pre-prefixed name
caused).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_resumes_and_skills"
down_revision: str | None = "0002_verification_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE processing_status AS ENUM "
        "('PENDING', 'EXTRACTING', 'PARSING', 'EMBEDDING', 'COMPLETE', 'FAILED')"
    )
    op.execute(
        "CREATE TYPE proficiency_level AS ENUM "
        "('BEGINNER', 'INTERMEDIATE', 'ADVANCED', 'EXPERT')"
    )

    # ------------------------------------------------------------ resumes
    op.create_table(
        "resumes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_resumes"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_resumes_user_id_users", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_resumes_user_id", "resumes", ["user_id"])
    op.create_index("ix_resumes_deleted_at", "resumes", ["deleted_at"])
    # "At most one primary resume per user" as a database rule rather than an
    # application convention that a background job could violate.
    op.create_index(
        "ux_resumes_one_primary",
        "resumes",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_primary AND deleted_at IS NULL"),
    )

    # ------------------------------------------------------------ resume_versions
    op.create_table(
        "resume_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resume_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("parsed_sections", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("parsed_entities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "processing_status",
            postgresql.ENUM(name="processing_status", create_type=False),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_resume_versions"),
        sa.ForeignKeyConstraint(
            ["resume_id"],
            ["resumes.id"],
            name="fk_resume_versions_resume_id_resumes",
            ondelete="CASCADE",
        ),
        # Mirrors the 5 MB API limit, so a direct database insert cannot create
        # a row the application would refuse.
        sa.CheckConstraint(
            "file_size_bytes > 0 AND file_size_bytes <= 5242880",
            name="file_size_within_limit",
        ),
        sa.CheckConstraint("version_number >= 1", name="version_number_positive"),
    )
    op.create_index(
        "ux_resume_versions_number", "resume_versions", ["resume_id", "version_number"], unique=True
    )
    # Supports skipping the pipeline when an identical file is re-uploaded.
    op.create_index("ix_resume_versions_hash", "resume_versions", ["content_hash"])

    # Added after resume_versions exists, since it points at it. Kept nullable
    # and without NOT NULL because a resume exists before its first version
    # finishes parsing.
    op.create_foreign_key(
        "fk_resumes_current_version_id_resume_versions",
        "resumes",
        "resume_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ------------------------------------------------------------ skills
    op.create_table(
        "skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("normalized_name", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("parent_skill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("demand_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_skills"),
        sa.UniqueConstraint("name", name="uq_skills_name"),
        sa.UniqueConstraint("normalized_name", name="uq_skills_normalized_name"),
        sa.ForeignKeyConstraint(
            ["parent_skill_id"],
            ["skills.id"],
            name="fk_skills_parent_skill_id_skills",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "demand_score IS NULL OR (demand_score >= 0 AND demand_score <= 1)",
            name="demand_score_is_fraction",
        ),
    )
    # Trigram index for fuzzy matching of near-miss spellings.
    op.create_index(
        "ix_skills_trgm",
        "skills",
        ["normalized_name"],
        postgresql_using="gin",
        postgresql_ops={"normalized_name": "gin_trgm_ops"},
    )
    # GIN over the alias array, so "does any skill list 'postgres'?" is an index
    # lookup rather than a scan.
    op.create_index("ix_skills_aliases", "skills", ["aliases"], postgresql_using="gin")
    op.create_index("ix_skills_category", "skills", ["category"])

    # ------------------------------------------------------------ candidate_skills
    op.create_table(
        "candidate_skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "proficiency", postgresql.ENUM(name="proficiency_level", create_type=False), nullable=True
        ),
        sa.Column("years_of_experience", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("extraction_confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "is_user_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("last_used_year", sa.SmallInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_skills"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_candidate_skills_user_id_users", ondelete="CASCADE"
        ),
        # RESTRICT: tidying the taxonomy must not silently delete part of
        # someone's profile.
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            name="fk_candidate_skills_skill_id_skills",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["resume_versions.id"],
            name="fk_candidate_skills_source_version_id_resume_versions",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "extraction_confidence IS NULL "
            "OR (extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="confidence_is_fraction",
        ),
        sa.CheckConstraint(
            "years_of_experience IS NULL OR years_of_experience >= 0",
            name="years_non_negative",
        ),
    )
    op.create_index("ux_candidate_skills", "candidate_skills", ["user_id", "skill_id"], unique=True)
    op.create_index("ix_candidate_skills_user", "candidate_skills", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_candidate_skills_user", table_name="candidate_skills")
    op.drop_index("ux_candidate_skills", table_name="candidate_skills")
    op.drop_table("candidate_skills")

    op.drop_index("ix_skills_category", table_name="skills")
    op.drop_index("ix_skills_aliases", table_name="skills")
    op.drop_index("ix_skills_trgm", table_name="skills")
    op.drop_table("skills")

    # Dropped before resume_versions, or the table it references cannot go.
    op.drop_constraint(
        "fk_resumes_current_version_id_resume_versions", "resumes", type_="foreignkey"
    )

    op.drop_index("ix_resume_versions_hash", table_name="resume_versions")
    op.drop_index("ux_resume_versions_number", table_name="resume_versions")
    op.drop_table("resume_versions")

    op.drop_index("ux_resumes_one_primary", table_name="resumes")
    op.drop_index("ix_resumes_deleted_at", table_name="resumes")
    op.drop_index("ix_resumes_user_id", table_name="resumes")
    op.drop_table("resumes")

    op.execute("DROP TYPE IF EXISTS proficiency_level")
    op.execute("DROP TYPE IF EXISTS processing_status")
