"""Indexing, and nearest-neighbour search over what it produced.

Against real PostgreSQL with real migrations, because the parts most likely to
be wrong are the pgvector column type, the HNSW index DDL and the `<=>` operator
— none of which a mock would exercise.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_embeddings_provider
from app.integrations.embeddings import FakeEmbeddingProvider
from app.models.embedding import JobEmbedding
from app.models.enums import JobStatus
from app.models.job import Job
from app.services.embedding.indexer import index_jobs

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

ALSO_BACKEND = """Backend Python Developer

About us
Acme Technologies builds payments infrastructure for teams in India.

Responsibilities
- Build and maintain backend services in Python
- Own PostgreSQL schemas end to end

Requirements
- 4+ years of professional backend experience
- Strong Python, FastAPI and PostgreSQL
"""

UNRELATED = """Registered Paediatric Nurse

About us
A childrens hospital ward in Chennai.

Responsibilities
- Provide bedside nursing care on the paediatric ward
- Administer medication and record patient observations

Requirements
- Registered nursing qualification
- Two years of ward experience
"""


async def submit(client: AsyncClient, headers: dict[str, str], title: str, text_: str) -> str:
    response = await client.post(
        f"{API}/jobs",
        headers=headers,
        json={
            "description": text_,
            "title": title,
            # Required since apply links shipped: a posting with no way to apply
            # is not one this product accepts.
            "source_url": f"https://jobs.example.com/{title.lower().replace(' ', '-')}",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["job"]["id"])


@pytest.fixture
def provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


class TestIndexing:
    async def test_embeds_the_backlog_and_stores_the_model_that_made_it(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        provider: FakeEmbeddingProvider,
    ) -> None:
        await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)

        result = await index_jobs(session=db_session, provider=provider, batch_size=10)

        assert result.embedded == 1
        row = (await db_session.scalars(select(JobEmbedding))).one()
        # Recorded on the row rather than assumed, because two model generations
        # have to be able to coexist while a backfill runs.
        assert row.model_name == provider.model_name
        assert row.dimensions == provider.dimensions
        assert len(row.embedding) == provider.dimensions

    async def test_a_second_pass_over_unchanged_text_calls_the_model_zero_times(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        provider: FakeEmbeddingProvider,
    ) -> None:
        """A repeat pass must cost no model time.

        Asserted on the *call count* rather than on a row timestamp, because a
        timestamp cannot distinguish "skipped" from "recomputed the identical
        answer" — and recomputing the corpus on every tick is exactly the failure
        this guards.

        Note it is the backlog query, not the hash, that does the work here:
        `considered` is 0 because the job already has a current vector. The hash
        is the second line of defence, for the over-eager case the next test
        exercises. Both have to hold for the worker to be idle when the corpus is.
        """
        await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await index_jobs(session=db_session, provider=provider, batch_size=10)
        calls_after_first = provider.calls

        second = await index_jobs(session=db_session, provider=provider, batch_size=10)

        assert second.embedded == 0
        assert provider.calls == calls_after_first

    async def test_re_embedding_replaces_the_row_rather_than_adding_one(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        provider: FakeEmbeddingProvider,
    ) -> None:
        """A changed document replaces its vector instead of adding a second.

        `updated_at` is moved by hand, and it has to be: PostgreSQL's `now()` is
        the *transaction* timestamp, so inside one transaction a freshly edited
        job and its vector carry byte-identical timestamps and the staleness
        predicate cannot fire. Editing the title alone would leave this test
        quietly asserting nothing.
        """
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await index_jobs(session=db_session, provider=provider, batch_size=10)

        job = await db_session.get(Job, job_id)
        assert job is not None
        job.title = "Staff Backend Engineer"
        job.updated_at = datetime.now(UTC) + timedelta(minutes=1)
        await db_session.flush()

        result = await index_jobs(session=db_session, provider=provider, batch_size=10)

        assert result.embedded == 1
        # on_conflict_do_update, so two workers racing produce one row rather
        # than an IntegrityError that kills the whole batch.
        assert len((await db_session.scalars(select(JobEmbedding))).all()) == 1

    async def test_the_hnsw_index_is_usable(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        provider: FakeEmbeddingProvider,
    ) -> None:
        """The index has to work, even though the planner will not choose it yet.

        At this corpus size a sequential scan is genuinely cheaper and the
        planner knows it, so the only way to prove the index is not merely
        *created* but *usable* is to take the alternative away. Without this,
        a broken `vector_cosine_ops` or a wrong `postgresql_using` would sit
        undetected until the corpus grew.
        """
        await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await index_jobs(session=db_session, provider=provider, batch_size=10)

        await db_session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = (
            await db_session.execute(
                text(
                    "EXPLAIN SELECT job_id FROM job_embeddings "
                    "ORDER BY embedding <=> (SELECT embedding FROM job_embeddings LIMIT 1) LIMIT 1"
                )
            )
        ).scalars()

        assert "ix_job_embeddings_hnsw" in "\n".join(plan)


class TestSimilarEndpoint:
    async def test_ranks_a_related_job_above_an_unrelated_one(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
    ) -> None:
        """The one assertion that says the feature works at all.

        Uses the same provider the API is overridden with, so the vectors the
        endpoint reads are the vectors this test indexed.
        """
        target = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        related = await submit(client, auth_headers, "Backend Python Developer", ALSO_BACKEND)
        await submit(client, auth_headers, "Registered Paediatric Nurse", UNRELATED)
        await index_jobs(session=db_session, provider=embedding_provider, batch_size=10)

        response = await client.get(f"{API}/jobs/{target}/similar", headers=auth_headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["availability"] == "READY"
        assert body["items"], "the related job should clear the similarity floor"
        assert body["items"][0]["job"]["id"] == related

    async def test_never_returns_the_job_itself(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
    ) -> None:
        # A job is always its own nearest neighbour at similarity 1.0, so this
        # is the one exclusion the query cannot be allowed to forget.
        target = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await submit(client, auth_headers, "Backend Python Developer", ALSO_BACKEND)
        await index_jobs(session=db_session, provider=embedding_provider, batch_size=10)

        response = await client.get(f"{API}/jobs/{target}/similar", headers=auth_headers)

        assert all(item["job"]["id"] != target for item in response.json()["items"])

    async def test_excludes_expired_and_inactive_postings(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
    ) -> None:
        target = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        related = await submit(client, auth_headers, "Backend Python Developer", ALSO_BACKEND)
        await index_jobs(session=db_session, provider=embedding_provider, batch_size=10)

        neighbour = await db_session.get(Job, related)
        assert neighbour is not None
        neighbour.expires_at = datetime.now(UTC) - timedelta(days=1)
        await db_session.flush()

        response = await client.get(f"{API}/jobs/{target}/similar", headers=auth_headers)

        assert response.json()["items"] == []

    async def test_says_pending_rather_than_empty_for_an_unindexed_job(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """ "Not indexed yet" and "nothing is similar" are different answers.

        Collapsing them into an empty list would make a feature that is simply
        behind look identical to one that ran and found nothing — which is the
        sort of thing that gets debugged twice.
        """
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)

        response = await client.get(f"{API}/jobs/{job_id}/similar", headers=auth_headers)

        assert response.json()["availability"] == "PENDING"
        assert response.json()["items"] == []

    async def test_says_disabled_when_no_provider_is_configured(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        # Through the transport, because the client fixture builds its own app
        # with create_app() and never exposes it — the same route test_jobs.py
        # already uses to switch off the jobs provider.
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        client._transport.app.dependency_overrides[get_embeddings_provider] = lambda: None  # type: ignore[attr-defined]

        response = await client.get(f"{API}/jobs/{job_id}/similar", headers=auth_headers)

        assert response.json()["availability"] == "DISABLED"

    async def test_unknown_job_is_404(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        import uuid

        response = await client.get(f"{API}/jobs/{uuid.uuid4()}/similar", headers=auth_headers)

        assert response.status_code == 404

    async def test_does_not_offer_a_duplicate_posting(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
    ) -> None:
        # A job marked DUPLICATE is hidden from browse, so offering it as a
        # neighbour would put it back in front of the user by a side door.
        target = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        related = await submit(client, auth_headers, "Backend Python Developer", ALSO_BACKEND)
        await index_jobs(session=db_session, provider=embedding_provider, batch_size=10)

        neighbour = await db_session.get(Job, related)
        assert neighbour is not None
        neighbour.status = JobStatus.DUPLICATE
        neighbour.canonical_job_id = target
        await db_session.flush()

        response = await client.get(f"{API}/jobs/{target}/similar", headers=auth_headers)

        assert response.json()["items"] == []
