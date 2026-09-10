"""Near-duplicate detection (ml.md section 5, US-3.2 AC2).

Against real PostgreSQL, because the parts most likely to be wrong are the
pg_trgm `%` operator, the model-equality join and the `<=>` ordering — none of
which a mock exercises.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.embeddings import FakeEmbeddingProvider
from app.models.enums import JobStatus
from app.models.job import Job
from app.services.embedding.indexer import index_jobs
from app.services.job.near_duplicate import DEFAULT_THRESHOLD, find_near_duplicates

API = "/api/v1"

BACKEND = """Senior Backend Engineer

About us
Zeta Labs builds payments infrastructure for teams across India.

Responsibilities
- Design and build backend services in Python
- Own services end to end, from schema to deploy

Requirements
- 5+ years of professional backend experience
- Strong Python, FastAPI and PostgreSQL
"""

#: The same role, reworded. No hash can match this, which is the entire reason
#: stage two exists.
BACKEND_REWORDED = """Senior Backend Engineer

About the company
Zeta Labs is building payment infrastructure for Indian teams.

What you will do
- Build and design Python backend services
- Take services from schema design through to deployment

What we need
- Five or more years of backend engineering
- Solid Python, FastAPI and PostgreSQL skills
"""

NURSING = """Registered Paediatric Nurse

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


class TestNearDuplicates:
    async def test_finds_the_same_role_reworded(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
    ) -> None:
        """The case stage one cannot catch.

        Different words, so a different `content_hash` and no exact match — but
        the same job. A low threshold is used because the hashing-trick fake
        produces lower cosines than the real model; what is asserted is that the
        reworded posting is found and the unrelated one is not.
        """
        original = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        reworded = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND_REWORDED)
        await submit(client, auth_headers, "Registered Paediatric Nurse", NURSING)
        await index_jobs(session=db_session, provider=embedding_provider, batch_size=10)

        found = await find_near_duplicates(
            session=db_session,
            job_id=uuid.UUID(original),
            model_name=embedding_provider.model_name,
            threshold=0.5,
        )

        assert [str(row.job_id) for row in found] == [reworded]
        assert found[0].similar_title is True

    async def test_never_returns_the_job_itself(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
    ) -> None:
        # A job is its own nearest neighbour at 1.0, so this is the one exclusion
        # the query cannot be allowed to forget — it would mark every posting a
        # duplicate of itself.
        original = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await submit(client, auth_headers, "Senior Backend Engineer", BACKEND_REWORDED)
        await index_jobs(session=db_session, provider=embedding_provider, batch_size=10)

        found = await find_near_duplicates(
            session=db_session,
            job_id=uuid.UUID(original),
            model_name=embedding_provider.model_name,
            threshold=0.0,
        )

        assert all(str(row.job_id) != original for row in found)

    async def test_scoping_excludes_an_unrelated_title_at_another_company(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
    ) -> None:
        """The scoping is what makes this affordable per ingest.

        Asserted with the threshold at zero, so the *only* thing that can
        exclude the nursing post is the company-or-similar-title scope. Without
        that assertion the test would pass on similarity alone and the scope
        could be silently dropped.
        """
        original = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        nursing = await submit(client, auth_headers, "Registered Paediatric Nurse", NURSING)
        await index_jobs(session=db_session, provider=embedding_provider, batch_size=10)

        found = await find_near_duplicates(
            session=db_session,
            job_id=uuid.UUID(original),
            model_name=embedding_provider.model_name,
            threshold=0.0,
        )

        assert nursing not in [str(row.job_id) for row in found]

    async def test_excludes_postings_already_marked_duplicate(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
    ) -> None:
        # Otherwise a cluster of three re-posts reports every pair among them and
        # a reviewer sees the same decision several times.
        original = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        reworded = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND_REWORDED)
        await index_jobs(session=db_session, provider=embedding_provider, batch_size=10)

        job = await db_session.get(Job, reworded)
        assert job is not None
        job.status = JobStatus.DUPLICATE
        job.canonical_job_id = uuid.UUID(original)
        await db_session.flush()

        found = await find_near_duplicates(
            session=db_session,
            job_id=uuid.UUID(original),
            model_name=embedding_provider.model_name,
            threshold=0.0,
        )

        assert found == []

    async def test_an_unindexed_job_returns_nothing_rather_than_raising(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
    ) -> None:
        original = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)

        found = await find_near_duplicates(
            session=db_session,
            job_id=uuid.UUID(original),
            model_name=embedding_provider.model_name,
        )

        assert found == []

    async def test_the_threshold_is_above_mls_specified_value(self) -> None:
        """Pins the deviation so it cannot drift back silently.

        ml.md specifies 0.95. The labelled evaluation found that admits
        same-company pairs differing only in seniority, at about 50% precision,
        so this sits above the highest observed false positive. The docstring in
        the module explains that two true duplicates cannot really justify a
        threshold — the value is where the evidence points, not where it is
        proven.
        """
        assert DEFAULT_THRESHOLD > 0.95

    @pytest.mark.parametrize("threshold", [0.99, 0.995])
    async def test_a_high_threshold_finds_nothing_in_a_reworded_pair(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        threshold: float,
    ) -> None:
        # The threshold has to actually gate. A detector that returns the same
        # candidates whatever it is set to is not using it.
        original = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await submit(client, auth_headers, "Senior Backend Engineer", BACKEND_REWORDED)
        await index_jobs(session=db_session, provider=embedding_provider, batch_size=10)

        found = await find_near_duplicates(
            session=db_session,
            job_id=uuid.UUID(original),
            model_name=embedding_provider.model_name,
            threshold=threshold,
        )

        assert found == []

    async def test_the_trigram_index_is_usable(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
    ) -> None:
        """The scoping depends on `ix_jobs_title_trgm` being real.

        At this corpus size the planner prefers a sequential scan, so the only
        way to show the index is usable rather than merely created is to take the
        alternative away. A wrong operator class would otherwise sit undetected
        until the corpus grew.
        """
        await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await index_jobs(session=db_session, provider=embedding_provider, batch_size=10)

        await db_session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            (
                await db_session.execute(
                    text(
                        "EXPLAIN SELECT id FROM jobs "
                        "WHERE normalized_title % 'senior backend engineer'"
                    )
                )
            ).scalars()
        )

        assert "ix_jobs_title_trgm" in plan
