"""Add PARTNER_API to job_source

Revision ID: 0006_job_source_partner_api
Revises: 0005_career_entities
Created: 2026-09-04

Restores a value docs/database.md specified from the start and 0004 shipped
without. It arrives now because live ingestion (US-3.4) needs a provenance of
its own — see ADR-019 for why reusing DATASET_IMPORT is not an option.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_job_source_partner_api"
down_revision: str | None = "0005_career_entities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL 12+ allows ALTER TYPE ... ADD VALUE inside a transaction block,
    # which env.py wraps every migration in, with one restriction: the new value
    # cannot be *used* in the same transaction that adds it. This migration only
    # adds it — no INSERT, no comparison — so the restriction does not bite.
    # IF NOT EXISTS keeps the statement re-runnable.
    op.execute("ALTER TYPE job_source ADD VALUE IF NOT EXISTS 'PARTNER_API'")


def downgrade() -> None:
    # PostgreSQL has no DROP VALUE, so the type has to be rebuilt. The USING
    # cast fails outright if any row still says PARTNER_API — deliberately.
    # Silently rewriting a row's provenance to DATASET_IMPORT would lose the
    # one fact that makes a provider's rows removable, which is worse than
    # refusing to downgrade.
    op.execute("ALTER TYPE job_source RENAME TO job_source_old")
    op.execute("CREATE TYPE job_source AS ENUM ('USER_SUBMITTED', 'DATASET_IMPORT')")
    op.execute(
        "ALTER TABLE jobs ALTER COLUMN source TYPE job_source USING source::text::job_source"
    )
    op.execute("DROP TYPE job_source_old")
