"""`skills.demand_score` — how commonly the live market asks for each skill.

Against real PostgreSQL, because the whole thing is one UPDATE with a correlated
count and the interesting cases are about *which* jobs it counts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import JobStatus
from app.models.job import Job
from app.models.skill import Skill
from app.services.job.demand import recompute_demand_scores

API = "/api/v1"

PYTHON_JOB = """Senior Backend Engineer

About us
Zeta Labs builds payments infrastructure for teams across India.

Responsibilities
- Design and build backend services in Python
- Own services end to end, from schema to deploy

Requirements
- 5+ years of professional backend experience
- Strong Python, FastAPI and PostgreSQL
"""

NURSING_JOB = """Registered Paediatric Nurse

About us
A childrens hospital ward in Chennai.

Responsibilities
- Provide bedside nursing care on the paediatric ward
- Administer medication and record patient observations

Requirements
- Registered nursing qualification
- Two years of ward experience
"""


async def submit(client: AsyncClient, headers: dict[str, str], title: str, body: str) -> str:
    response = await client.post(
        f"{API}/jobs",
        headers=headers,
        json={
            "description": body,
            "title": title,
            "source_url": f"https://jobs.example.com/{uuid.uuid4()}",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["job"]["id"])


async def demand_for(session: AsyncSession, name: str):
    return await session.scalar(select(Skill.demand_score).where(Skill.name == name))


class TestRecompute:
    async def test_scores_every_skill_so_never_computed_is_distinguishable(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """A skill no live job wants gets 0, not NULL.

        `score_skill` treats NULL as "fall back to flat weights" and 0 as a real
        answer. Leaving unwanted skills NULL would silently disable the rarity
        weighting for them, which is the opposite of what their rarity deserves.
        """
        await submit(client, auth_headers, "Senior Backend Engineer", PYTHON_JOB)

        scored, total, highest = await recompute_demand_scores(db_session)

        assert scored == total == seeded_skills
        assert highest is not None and highest > 0

        # Asserted as a property rather than by naming a skill: which taxonomy
        # entries a fixture happens to mention is incidental, and hard-coding one
        # makes the test fail when the seed list changes rather than when the
        # behaviour does.
        unscored = await db_session.scalar(
            select(func.count()).select_from(Skill).where(Skill.demand_score.is_(None))
        )
        at_zero = await db_session.scalar(
            select(func.count()).select_from(Skill).where(Skill.demand_score == 0)
        )
        assert unscored == 0, "every skill must be scored, or NULL stops meaning 'never computed'"
        assert at_zero > 0, "one posting cannot possibly want all 267 skills"

    async def test_a_skill_in_every_job_scores_one(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        await submit(client, auth_headers, "Senior Backend Engineer", PYTHON_JOB)

        await recompute_demand_scores(db_session)

        assert await demand_for(db_session, "Python") == 1
        assert await demand_for(db_session, "FastAPI") == 1

    async def test_the_fraction_tracks_the_corpus(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """Two jobs, one of them Python, so Python is 0.5 rather than 1.

        This is the behaviour the weighting depends on: the score has to be a
        share of the market, not a count.
        """
        await submit(client, auth_headers, "Senior Backend Engineer", PYTHON_JOB)
        await submit(client, auth_headers, "Registered Paediatric Nurse", NURSING_JOB)

        await recompute_demand_scores(db_session)

        assert await demand_for(db_session, "Python") == Decimal("0.5")

    async def test_counts_only_live_postings(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """Expired and duplicate postings are not demand.

        A skill every *closed* job wanted is not what the market wants now, and
        counting them would keep a dead technology weighted as commonplace long
        after anyone stopped hiring for it.
        """
        await submit(client, auth_headers, "Senior Backend Engineer", PYTHON_JOB)
        stale = await submit(client, auth_headers, "Registered Paediatric Nurse", NURSING_JOB)

        # With both live, Python is a half — that is the control.
        await recompute_demand_scores(db_session)
        assert await demand_for(db_session, "Python") == Decimal("0.5")

        expired = await db_session.get(Job, stale)
        assert expired is not None
        expired.expires_at = datetime.now(UTC) - timedelta(days=1)
        await db_session.flush()

        await recompute_demand_scores(db_session)

        # One live posting, and it wants Python.
        assert await demand_for(db_session, "Python") == 1

    async def test_a_duplicate_posting_does_not_inflate_demand(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        survivor = await submit(client, auth_headers, "Senior Backend Engineer", PYTHON_JOB)
        other = await submit(client, auth_headers, "Registered Paediatric Nurse", NURSING_JOB)

        await recompute_demand_scores(db_session)
        assert await demand_for(db_session, "Python") == Decimal("0.5")

        marked = await db_session.get(Job, other)
        assert marked is not None
        marked.status = JobStatus.DUPLICATE
        # The CHECK constraint requires a DUPLICATE to name what it duplicates.
        marked.canonical_job_id = uuid.UUID(survivor)
        await db_session.flush()

        await recompute_demand_scores(db_session)

        # A duplicate is one opening counted twice, so it must not move demand.
        assert await demand_for(db_session, "Python") == 1

    async def test_an_empty_corpus_leaves_scores_null_rather_than_dividing_by_zero(
        self, db_session: AsyncSession, seeded_skills: int
    ) -> None:
        scored, total, highest = await recompute_demand_scores(db_session)

        assert scored == 0
        assert total == seeded_skills
        assert highest is None


