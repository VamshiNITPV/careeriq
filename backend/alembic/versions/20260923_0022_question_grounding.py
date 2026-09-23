"""Keep the grounding a question claimed, and whether it degraded (US-8.1 AC1)

Revision ID: 0022_question_grounding
Revises: 0021_interviews
Created: 2026-09-23

Two columns that 0021 should have carried.

`questions.py` validates that the words a question claims to build on are really
in the candidate's resume, and then **threw the claim away**. The gate still
worked -- nothing ungrounded was ever stored -- but the evidence for it did not
survive, so "this was built on your line about the ledger migration" was
unanswerable a second after the question appeared. A grounding nobody can
inspect afterwards is a grounding nobody can audit.

`degraded` is worse than an omission: the module's own docstring says the
fallback is "recorded so a report can say the personalisation did not hold", and
it was only logged. A promise kept in a log file is not kept -- a report reads
rows.

Found by running the feature against the real model and reading the row it
wrote, which is the only way either would have shown up: every test passed
either way, because nothing asserted on a column that did not exist.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_question_grounding"
down_revision: str | None = "0021_interviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interview_questions",
        # Nullable: a question need not build on anything specific, and
        # requiring it would push the model to invent a connection -- the
        # opposite of what the gate exists for.
        sa.Column("grounded_in", sa.Text(), nullable=True),
    )
    op.add_column(
        "interview_questions",
        sa.Column(
            "degraded",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("interview_questions", "degraded")
    op.drop_column("interview_questions", "grounded_in")
