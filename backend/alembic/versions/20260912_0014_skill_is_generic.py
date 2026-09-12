"""Add skills.is_generic — believe a vague term only where skills are listed

Revision ID: 0014_skill_is_generic
Revises: 0013_candidate_skill_rejected
Created: 2026-09-12

The skill-extraction evaluation put precision at 0.703 against a 0.85 target, and
found the whole shortfall in one place: entries that are real skills *and*
ordinary words in a job description. `Security` was counted a false positive in
ten postings, `Deployment` in seven, `Scalability` in seven — and in every case
the word was genuinely in the text. "Optimize application performance,
scalability, and security" describes the work; it does not say the employer wants
Security as a skill, and no reader would list it as one.

The same mechanism produced a problem Phase 6.5 met from the other side, where
`Communication` appeared in 45% of postings and flattened the ranking's skill
dimension. Rarity weighting treated the symptom.

This column marks those entries so extraction can require them to appear where
skills are actually *listed* — a resume's Skills block, a posting's Requirements
block — rather than anywhere in prose. **Marking, not deleting**: someone whose
resume says "Security" under Skills is claiming it, and that must still be found.
The flag narrows where the term is believed, not whether it exists.

Backfilled from `SEED_SKILLS`, which is the curation source. Skills created from
user input are never generic — a term someone typed into their own profile is a
claim by definition.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_skill_is_generic"
down_revision: str | None = "0013_candidate_skill_rejected"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skills",
        sa.Column("is_generic", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # Backfilled by name rather than left to the next seeder run, so the column
    # is correct the moment the migration finishes. `seed_skill_taxonomy` also
    # writes it and is idempotent, so the two agree.
    generic = (
        "Security",
        "Software Testing",
        "Deployment",
        "Performance Optimization",
        "Scalability",
        "Software Engineering",
        "Technical Documentation",
        "Backend Development",
        "Frontend Development",
        "Responsive Web Design",
        "Caching",
        "System Design",
        "Code Review",
        "Debugging",
        "Database Design",
        "Authentication",
        "DevOps",
        "MLOps",
        "Communication",
        "Leadership",
        "Teamwork",
        "Problem Solving",
        "Mentoring",
        "Project Management",
        "Time Management",
        "Critical Thinking",
        "Adaptability",
        "Stakeholder Management",
    )
    op.execute(
        sa.text("UPDATE skills SET is_generic = true WHERE name = ANY(:names)").bindparams(
            sa.bindparam("names", value=list(generic), type_=sa.ARRAY(sa.String))
        )
    )


def downgrade() -> None:
    op.drop_column("skills", "is_generic")
