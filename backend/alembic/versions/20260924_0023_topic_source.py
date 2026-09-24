"""Where an interview's topics came from (US-8.1 AC1)

Revision ID: 0023_topic_source
Revises: 0022_question_grounding
Created: 2026-09-24

`blueprint.py` has always known which of three sources produced an interview's
topics, and has always thrown the answer away -- its docstring claimed the value
"reaches the API so a user is not shown 'based on what employers want' over a
generic list", and nothing carried it past the function that computed it.

These two columns are that claim made true. Recorded on the row rather than
recomputed on read, for the reason `interview_scores.next_difficulty` records:
the corpus grows, and a transcript read next month should say what its questions
were actually built from, not what today's corpus would produce.

Both nullable. Null is not a missing value here -- it is an interview whose first
question has not been generated yet, which lasts a few seconds and is a real
state a client can see.

The enum is created with an explicit CREATE TYPE rather than being inferred from
the column, for the reason 0001 records and 0021 repeats: SQLAlchemy emits
CREATE TYPE inline inside CREATE TABLE, which fails the second time anything runs.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_topic_source"
down_revision: str | None = "0022_question_grounding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ordered most specific to least, which is also the order `blueprint_for`
    # prefers them in. The order is documentation here rather than behaviour --
    # nothing compares these -- but a reader should not have to guess.
    op.execute(
        "CREATE TYPE interview_topic_source AS ENUM "
        "('THIS_JOB', 'ROLE_DEMAND', 'GENERIC')"
    )

    op.add_column(
        "interviews",
        sa.Column(
            "topic_source",
            postgresql.ENUM(
                "THIS_JOB",
                "ROLE_DEMAND",
                "GENERIC",
                name="interview_topic_source",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "interviews",
        sa.Column("topic_postings", sa.SmallInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("interviews", "topic_postings")
    op.drop_column("interviews", "topic_source")
    # After the column, not before: Postgres refuses to drop a type still in use.
    op.execute("DROP TYPE interview_topic_source")
