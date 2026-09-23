"""The adaptive interview and its transcript (database.md 3.8, ADR-013)

Revision ID: 0021_interviews
Revises: 0020_application_snapshot
Created: 2026-09-23

Four tables and two enums. The schema is ADR-013's decision written down: the
interview's state lives in `interviews.current_difficulty` and
`topics_covered`, not in a model's context window, which is what makes a session
resumable (US-8.1 AC2) and the adaptation policy testable with no model at all.

Nothing reads these yet. The tables and the deterministic policy come first
precisely so the trajectory can be proven before any prompt exists -- 9.2 adds
question generation on top of a state machine that is already correct.

Enums are created with an explicit CREATE TYPE rather than being inferred from
the columns, for the reason 0001 records: SQLAlchemy emits CREATE TYPE inline
inside CREATE TABLE, which fails the second time anything runs.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_interviews"
down_revision: str | None = "0020_application_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE interview_status AS ENUM "
        "('CREATED', 'IN_PROGRESS', 'COMPLETED', 'ABANDONED')"
    )
    # Ordered easiest to hardest. The policy steps along this ladder, so the
    # order is behaviour rather than presentation.
    op.execute("CREATE TYPE question_difficulty AS ENUM ('EASY', 'MEDIUM', 'HARD', 'EXPERT')")

    op.create_table(
        "interviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        # SET NULL: deleting an application must not delete the record that you
        # practised for it.
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Free text. An interview can be practice for a role no posting in the
        # corpus has ever carried.
        sa.Column("target_role", sa.Text(), nullable=False),
        sa.Column("target_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="interview_status", create_type=False),
            server_default=sa.text("'CREATED'::interview_status"),
            nullable=False,
        ),
        # ---- the state machine (ADR-013) ----
        sa.Column(
            "current_difficulty",
            postgresql.ENUM(name="question_difficulty", create_type=False),
            server_default=sa.text("'MEDIUM'::question_difficulty"),
            nullable=False,
        ),
        sa.Column(
            "topics_covered",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "question_budget",
            sa.SmallInteger(),
            server_default=sa.text("10"),
            nullable=False,
        ),
        sa.Column(
            "questions_asked", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        # ---- the report, all null until it completes ----
        sa.Column("overall_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("dimension_scores", postgresql.JSONB(), nullable=True),
        sa.Column("summary_feedback", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        # A budget of zero ends the interview before it starts; a negative one
        # never terminates under a `questions_asked >= budget` check.
        sa.CheckConstraint("question_budget > 0", name=op.f("ck_interviews_budget_positive")),
        sa.CheckConstraint("questions_asked >= 0", name=op.f("ck_interviews_asked_not_negative")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_interviews_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_interviews_application_id_applications"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_job_id"],
            ["jobs.id"],
            name=op.f("fk_interviews_target_job_id_jobs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interviews")),
    )
    op.create_index(
        op.f("ix_interviews_user_created"), "interviews", ["user_id", "created_at"]
    )

    op.create_table(
        "interview_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("interview_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_order", sa.SmallInteger(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column(
            "difficulty",
            postgresql.ENUM(name="question_difficulty", create_type=False),
            nullable=False,
        ),
        # The rubric, fixed before the answer exists -- which is what lets the
        # scorer judge against stated criteria rather than an impression.
        sa.Column(
            "expected_points",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("generated_by", sa.Text(), nullable=True),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["interview_id"],
            ["interviews.id"],
            name=op.f("fk_interview_questions_interview_id_interviews"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_questions")),
    )
    # Without this a retry writes two question 3s and the transcript loses its
    # order -- which breaks the report and the difficulty trajectory US-8.2 AC2
    # asks to show.
    op.create_index(
        "ux_interview_questions_order",
        "interview_questions",
        ["interview_id", "question_order"],
        unique=True,
    )

    op.create_table(
        "interview_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        # UNIQUE: the score hangs off the answer, so a second answer to one
        # question would give it two scores and double its weight in the report.
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.SmallInteger(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["interview_questions.id"],
            name=op.f("fk_interview_answers_question_id_interview_questions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_answers")),
        sa.UniqueConstraint("question_id", name=op.f("uq_interview_answers_question_id")),
    )

    op.create_table(
        "interview_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("answer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("technical_score", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("relevance_score", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("completeness_score", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("communication_score", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("structure_score", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("overall_score", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column(
            "strengths",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "improvements",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        # Character offsets, not quoted excerpts: an offset either lands on the
        # user's own words or is detectably out of range, where a quote could be
        # paraphrased without anybody noticing (US-8.3 AC2).
        sa.Column("cited_spans", postgresql.JSONB(), nullable=True),
        sa.Column(
            "next_difficulty",
            postgresql.ENUM(name="question_difficulty", create_type=False),
            nullable=True,
        ),
        sa.Column("scored_by", sa.Text(), nullable=True),
        # Null except on evaluation rows. On this row rather than a spreadsheet
        # so model-vs-human agreement is one query (ADR-015, US-8.3 AC3).
        sa.Column("human_score", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        # A value outside 0..1 is not a low score, it is a parsing failure --
        # and it would reach the averages and the agreement metric looking like
        # a result.
        sa.CheckConstraint(
            "technical_score BETWEEN 0 AND 1 AND relevance_score BETWEEN 0 AND 1 "
            "AND completeness_score BETWEEN 0 AND 1 AND communication_score BETWEEN 0 AND 1 "
            "AND structure_score BETWEEN 0 AND 1 AND overall_score BETWEEN 0 AND 1",
            name=op.f("ck_interview_scores_in_range"),
        ),
        sa.CheckConstraint(
            "human_score IS NULL OR human_score BETWEEN 0 AND 1",
            name=op.f("ck_interview_scores_human_in_range"),
        ),
        sa.ForeignKeyConstraint(
            ["answer_id"],
            ["interview_answers.id"],
            name=op.f("fk_interview_scores_answer_id_interview_answers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_scores")),
        sa.UniqueConstraint("answer_id", name=op.f("uq_interview_scores_answer_id")),
    )


def downgrade() -> None:
    # Tables before types: a type cannot be dropped while a column still uses it.
    op.drop_table("interview_scores")
    op.drop_table("interview_answers")
    op.drop_index("ux_interview_questions_order", table_name="interview_questions")
    op.drop_table("interview_questions")
    op.drop_index(op.f("ix_interviews_user_created"), table_name="interviews")
    op.drop_table("interviews")
    op.execute("DROP TYPE question_difficulty")
    op.execute("DROP TYPE interview_status")
