"""Add companies, jobs, and job skill requirements

Revision ID: 0004_jobs_and_companies
Revises: 0003_resumes_and_skills
Created: 2026-09-03

Check constraints use bare names — the metadata naming convention prepends
ck_<table>_ to whatever is supplied (see 0001 for the drift a pre-prefixed name
caused).

work_mode, employment_type, experience_level, education_level and
processing_status already exist from earlier revisions and are referenced with
create_type=False rather than recreated.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_jobs_and_companies"
down_revision: str | None = "0003_resumes_and_skills"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str) -> postgresql.ENUM:
    """Reference an already-created type without attempting to create it."""
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    op.execute("CREATE TYPE job_source AS ENUM ('USER_SUBMITTED', 'DATASET_IMPORT')")
    op.execute("CREATE TYPE job_status AS ENUM ('ACTIVE', 'DUPLICATE')")
    op.execute("CREATE TYPE skill_requirement AS ENUM ('REQUIRED', 'PREFERRED')")
    op.execute("CREATE TYPE salary_period AS ENUM ('YEARLY', 'MONTHLY', 'HOURLY')")

    # ------------------------------------------------------------ companies
    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("size_range", sa.String(length=50), nullable=True),
        sa.Column("headquarters", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_companies"),
        sa.UniqueConstraint("normalized_name", name="uq_companies_normalized_name"),
    )

    # ------------------------------------------------------------ jobs
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", _enum("job_source"), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("normalized_title", sa.String(length=300), nullable=True),
        sa.Column("description_raw", sa.Text(), nullable=False),
        sa.Column("description_clean", sa.Text(), nullable=True),
        sa.Column(
            "responsibilities",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "requirements",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "benefits",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("work_mode", _enum("work_mode"), nullable=True),
        sa.Column("employment_type", _enum("employment_type"), nullable=True),
        sa.Column("experience_level", _enum("experience_level"), nullable=True),
        sa.Column("min_years_experience", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("max_years_experience", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("min_education", _enum("education_level"), nullable=True),
        sa.Column("salary_min", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("salary_max", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("salary_currency", sa.String(length=3), nullable=True),
        sa.Column("salary_period", _enum("salary_period"), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("canonical_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status", _enum("job_status"), server_default=sa.text("'ACTIVE'::job_status"), nullable=False
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "parsing_status",
            _enum("processing_status"),
            server_default=sa.text("'PENDING'::processing_status"),
            nullable=False,
        ),
        sa.Column("parsing_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_jobs_company_id_companies",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_user_id"],
            ["users.id"],
            name="fk_jobs_submitted_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_max >= salary_min",
            name="salary_range_ordered",
        ),
        sa.CheckConstraint(
            "min_years_experience IS NULL OR max_years_experience IS NULL "
            "OR max_years_experience >= min_years_experience",
            name="years_range_ordered",
        ),
        sa.CheckConstraint(
            "salary_currency IS NULL OR char_length(salary_currency) = 3",
            name="currency_is_iso4217",
        ),
        sa.CheckConstraint(
            "country_code IS NULL OR char_length(country_code) = 2",
            name="country_is_iso3166",
        ),
        # A DUPLICATE with no canonical is a row nothing can resolve; an ACTIVE
        # one claiming a canonical is a contradiction.
        sa.CheckConstraint(
            "(status = 'DUPLICATE') = (canonical_job_id IS NOT NULL)",
            name="duplicate_has_canonical",
        ),
        sa.CheckConstraint("canonical_job_id IS NULL OR canonical_job_id <> id", name="not_self_dupe"),
    )

    # Self-referential, added after the table exists.
    op.create_foreign_key(
        "fk_jobs_canonical_job_id",
        "jobs",
        "jobs",
        ["canonical_job_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Partial: ranking only reads live postings, so the index stays small as
    # duplicates accumulate.
    op.create_index(
        "ix_jobs_active",
        "jobs",
        ["status", sa.text("posted_at DESC")],
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index("ix_jobs_content_hash", "jobs", ["content_hash"])
    op.create_index(
        "ix_jobs_title_trgm",
        "jobs",
        ["normalized_title"],
        postgresql_using="gin",
        postgresql_ops={"normalized_title": "gin_trgm_ops"},
    )
    op.create_index("ix_jobs_location", "jobs", ["country_code", "location"])
    op.create_index("ix_jobs_company", "jobs", ["company_id"])
    # What makes re-running an import create nothing new (US-3.3 AC1). Partial,
    # because a user paste has no external id and many such rows may exist.
    op.create_index(
        "ux_jobs_external",
        "jobs",
        ["source", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

    # ------------------------------------------------------------ job_skills
    op.create_table(
        "job_skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requirement", _enum("skill_requirement"), nullable=False),
        sa.Column("min_years", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("extraction_confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_job_skills"),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_job_skills_job_id_jobs", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"], name="fk_job_skills_skill_id_skills", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "extraction_confidence IS NULL "
            "OR (extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="confidence_is_fraction",
        ),
        sa.CheckConstraint("min_years IS NULL OR min_years >= 0", name="min_years_non_negative"),
    )
    op.create_index("ux_job_skills", "job_skills", ["job_id", "skill_id"], unique=True)
    # Powers demand_score and gap severity (US-5.1 AC2).
    op.create_index("ix_job_skills_skill", "job_skills", ["skill_id", "requirement"])


def downgrade() -> None:
    op.drop_table("job_skills")
    op.drop_constraint("fk_jobs_canonical_job_id", "jobs", type_="foreignkey")
    op.drop_table("jobs")
    op.drop_table("companies")
    op.execute("DROP TYPE salary_period")
    op.execute("DROP TYPE skill_requirement")
    op.execute("DROP TYPE job_status")
    op.execute("DROP TYPE job_source")
