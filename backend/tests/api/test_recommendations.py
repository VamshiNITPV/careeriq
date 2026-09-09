"""`GET /recommendations` — two-stage retrieval, end to end (US-4.1, ADR-006).

Against real PostgreSQL, because the parts most likely to be wrong are the ones
a mock cannot exercise: the HNSW recall query, its hard filters, and whether the
ranked list agrees with the per-job endpoint.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_embeddings_provider
from app.integrations.embeddings import FakeEmbeddingProvider
from app.models.enums import JobStatus, RecommendationFeedback
from app.models.job import Job
from app.models.recommendation import RecommendationFeedbackRow
from app.services.embedding.indexer import index_candidates, index_jobs
from app.services.matching.recall import OVERFETCH, RECALL_LIMIT
from tests.fixtures.documents import build_pdf

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


async def submit(client: AsyncClient, headers: dict[str, str], title: str, body: str) -> str:
    response = await client.post(
        f"{API}/jobs",
        headers=headers,
        json={
            "description": body,
            "title": title,
            "source_url": f"https://jobs.example.com/{title.lower().replace(' ', '-')}",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["job"]["id"])


async def upload_resume(client: AsyncClient, headers: dict[str, str], run_pipeline) -> None:
    """Upload and parse. The pipeline sets `current_version_id`, which is what
    `default_resume_version_id` reads — an unparsed upload answers NO_RESUME."""
    response = await client.post(
        f"{API}/resumes",
        headers=headers,
        files={"file": ("resume.pdf", build_pdf(), "application/pdf")},
    )
    assert response.status_code == 202, response.text
    await run_pipeline(uuid.UUID(response.json()["version_id"]))


async def index_everything(
    session: AsyncSession, provider: FakeEmbeddingProvider
) -> None:
    await index_jobs(session=session, provider=provider, batch_size=500)
    await index_candidates(session=session, provider=provider, batch_size=50)


class TestAvailability:
    async def test_no_resume_is_a_stated_answer_not_an_empty_list(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        response = await client.get(f"{API}/recommendations", headers=auth_headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["availability"] == "NO_RESUME"
        assert body["items"] == []

    async def test_pending_when_the_resume_has_no_vector_yet(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """"Not indexed yet" and "nothing matched" are different answers.

        Collapsing them into an empty list makes a feature that is merely behind
        look identical to one that is broken — the same distinction `/similar`
        draws, for the same reason.
        """
        await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)

        body = (await client.get(f"{API}/recommendations", headers=auth_headers)).json()

        assert body["availability"] == "PENDING"
        assert body["items"] == []

    async def test_pending_when_no_provider_is_configured(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        await upload_resume(client, auth_headers, run_pipeline)
        client._transport.app.dependency_overrides[get_embeddings_provider] = lambda: None  # type: ignore[attr-defined]

        body = (await client.get(f"{API}/recommendations", headers=auth_headers)).json()

        assert body["availability"] == "PENDING"

    async def test_ready_once_both_sides_are_indexed(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        run_pipeline,
    ) -> None:
        await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await submit(client, auth_headers, "Registered Paediatric Nurse", UNRELATED)
        await upload_resume(client, auth_headers, run_pipeline)
        await index_everything(db_session, embedding_provider)

        body = (await client.get(f"{API}/recommendations", headers=auth_headers)).json()

        assert body["availability"] == "READY"
        assert len(body["items"]) == 2
        assert body["ranking_version"] == "v1-hand-tuned"

    async def test_someone_elses_resume_version_is_404(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        response = await client.get(
            f"{API}/recommendations?resume_version_id={uuid.uuid4()}", headers=auth_headers
        )
        assert response.status_code == 404


class TestRanking:
    async def test_a_related_job_outranks_an_unrelated_one(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        run_pipeline,
    ) -> None:
        """The assertion that says the feature works at all.

        The sample resume is a Python backend engineer's. If a paediatric
        nursing post is not last, the ranking is not ranking.
        """
        backend = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await submit(client, auth_headers, "Backend Python Developer", ALSO_BACKEND)
        nursing = await submit(client, auth_headers, "Registered Paediatric Nurse", UNRELATED)
        await upload_resume(client, auth_headers, run_pipeline)
        await index_everything(db_session, embedding_provider)

        items = (await client.get(f"{API}/recommendations", headers=auth_headers)).json()["items"]

        ordered = [item["job"]["id"] for item in items]
        assert ordered[-1] == nursing
        assert backend in ordered[:2]
        # Descending, and asserted rather than assumed — a list that is not
        # sorted is not a ranking, whatever its contents.
        scores = [Decimal(item["score"]) for item in items]
        assert scores == sorted(scores, reverse=True)

    async def test_the_list_score_equals_the_job_pages_score(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        run_pipeline,
    ) -> None:
        """The single most valuable check in this phase.

        If a job shows 68 in the list and 61 on its own page, one of them is
        lying and a reader has no way to tell which. Both paths run the same
        `_score`, and this is what keeps that true after someone edits one of
        them.
        """
        await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await submit(client, auth_headers, "Registered Paediatric Nurse", UNRELATED)
        await upload_resume(client, auth_headers, run_pipeline)
        await index_everything(db_session, embedding_provider)

        items = (await client.get(f"{API}/recommendations", headers=auth_headers)).json()["items"]
        assert items

        for item in items:
            job_id = item["job"]["id"]
            single = (
                await client.get(f"{API}/jobs/{job_id}/match", headers=auth_headers)
            ).json()
            assert Decimal(item["score"]) == Decimal(single["overall_score"]), job_id
            assert [row["reason"] for row in item["breakdown"]] == [
                row["reason"] for row in single["breakdown"]
            ], job_id

    async def test_contributions_still_sum_to_the_score_in_the_list(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        run_pipeline,
    ) -> None:
        await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)
        await index_everything(db_session, embedding_provider)

        items = (await client.get(f"{API}/recommendations", headers=auth_headers)).json()["items"]

        for item in items:
            total = sum(Decimal(row["contribution"]) for row in item["breakdown"])
            assert total == Decimal(item["score"])

    async def test_min_score_filters_the_list(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        run_pipeline,
    ) -> None:
        await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await submit(client, auth_headers, "Registered Paediatric Nurse", UNRELATED)
        await upload_resume(client, auth_headers, run_pipeline)
        await index_everything(db_session, embedding_provider)

        everything = (
            await client.get(f"{API}/recommendations", headers=auth_headers)
        ).json()["items"]
        floor = max(Decimal(item["score"]) for item in everything)

        filtered = (
            await client.get(f"{API}/recommendations?min_score={floor}", headers=auth_headers)
        ).json()["items"]

        assert len(filtered) < len(everything)
        assert all(Decimal(item["score"]) >= floor for item in filtered)


class TestRecallFilters:
    async def test_excludes_a_job_the_user_has_applied_to(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        run_pipeline,
    ) -> None:
        applied = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await submit(client, auth_headers, "Backend Python Developer", ALSO_BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)
        await index_everything(db_session, embedding_provider)

        marked = await client.put(
            f"{API}/jobs/{applied}/application",
            headers=auth_headers,
            json={"status": "APPLIED"},
        )
        assert marked.status_code in (200, 201), marked.text

        default = (await client.get(f"{API}/recommendations", headers=auth_headers)).json()
        assert applied not in [item["job"]["id"] for item in default["items"]]

        # And the opt-out works, so a user can still see what they applied to.
        included = (
            await client.get(f"{API}/recommendations?exclude_applied=false", headers=auth_headers)
        ).json()
        assert applied in [item["job"]["id"] for item in included["items"]]

    async def test_a_saved_job_is_still_recommended(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        run_pipeline,
    ) -> None:
        """Saved is not applied.

        Bookmarking a job is interest, not completion — hiding it from the
        ranking would punish the user for the one signal they gave us.
        """
        saved = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)
        await index_everything(db_session, embedding_provider)

        await client.put(
            f"{API}/jobs/{saved}/application", headers=auth_headers, json={"status": "SAVED"}
        )

        body = (await client.get(f"{API}/recommendations", headers=auth_headers)).json()
        assert saved in [item["job"]["id"] for item in body["items"]]

    async def test_excludes_expired_and_non_active_postings(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        run_pipeline,
    ) -> None:
        expired = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        duplicate = await submit(client, auth_headers, "Backend Python Developer", ALSO_BACKEND)
        survivor = await submit(client, auth_headers, "Registered Paediatric Nurse", UNRELATED)
        await upload_resume(client, auth_headers, run_pipeline)
        await index_everything(db_session, embedding_provider)

        stale = await db_session.get(Job, expired)
        assert stale is not None
        stale.expires_at = datetime.now(UTC) - timedelta(days=1)
        dupe = await db_session.get(Job, duplicate)
        assert dupe is not None
        dupe.status = JobStatus.DUPLICATE
        dupe.canonical_job_id = survivor
        await db_session.flush()

        body = (await client.get(f"{API}/recommendations", headers=auth_headers)).json()

        assert [item["job"]["id"] for item in body["items"]] == [survivor]

    async def test_the_recall_query_uses_the_hnsw_index(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        run_pipeline,
    ) -> None:
        """The planner will not choose HNSW at this corpus size, so prove it is
        *usable* by taking the alternative away.

        Without this, a wrong operator class or a rewritten ORDER BY would turn
        stage one into a sequential scan and nothing would go red until the
        corpus was large enough for it to matter.
        """
        await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)
        await index_everything(db_session, embedding_provider)

        await db_session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            (
                await db_session.execute(
                    text(
                        "EXPLAIN SELECT je.job_id FROM job_embeddings je "
                        "ORDER BY je.embedding <=> "
                        "(SELECT ce.embedding FROM candidate_embeddings ce LIMIT 1) LIMIT 200"
                    )
                )
            ).scalars()
        )

        assert "ix_job_embeddings_hnsw" in plan

    def test_the_recall_overfetches_before_filtering(self) -> None:
        """pgvector applies relational filters *after* the approximate scan, so
        a bare LIMIT 200 over a corpus with expired or applied-to postings comes
        back short — quietly, with the missing rows being exactly the ones stage
        two would have ranked. This is the direct threat to ml.md's Recall@200
        target, so the multiplier is pinned rather than left to drift."""
        assert OVERFETCH >= 2
        assert RECALL_LIMIT == 200


class TestPaging:
    async def test_pages_cover_the_list_exactly_once(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        run_pipeline,
    ) -> None:
        """No row served twice, none skipped.

        The failure this guards is silent: with an unstable sort a row appears
        on two consecutive pages or on neither, and nothing errors.
        """
        # Each description must differ. `content_hash` dedup is keyed on the
        # cleaned description, not the title, so six copies of one posting under
        # six titles collapse into a single job and there is nothing to page.
        for index in range(6):
            await submit(
                client,
                auth_headers,
                f"Backend Engineer {index}",
                BACKEND.replace("Zeta Labs", f"Zeta Labs {index}"),
            )
        await upload_resume(client, auth_headers, run_pipeline)
        await index_everything(db_session, embedding_provider)

        seen: list[str] = []
        cursor: str | None = None
        for _ in range(10):  # bounded, so a paging bug cannot loop forever
            url = f"{API}/recommendations?limit=2"
            if cursor is not None:
                url += f"&cursor={cursor}"
            body = (await client.get(url, headers=auth_headers)).json()
            seen.extend(item["job"]["id"] for item in body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                break

        assert cursor is None, "paging did not terminate"
        assert len(seen) == len(set(seen)) == 6

    async def test_no_cursor_on_the_last_page(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        run_pipeline,
    ) -> None:
        # A cursor that is always present makes a client fetch an empty response
        # just to discover it has finished.
        await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)
        await index_everything(db_session, embedding_provider)

        body = (await client.get(f"{API}/recommendations?limit=20", headers=auth_headers)).json()

        assert body["items"]
        assert body["next_cursor"] is None

    async def test_a_junk_cursor_starts_from_the_beginning_rather_than_500ing(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        run_pipeline,
    ) -> None:
        """A cursor travels in a URL, so it can be truncated by a mail client or
        simply invented. None of that is worth a 500."""
        await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)
        await index_everything(db_session, embedding_provider)

        response = await client.get(
            f"{API}/recommendations?cursor=not-a-real-cursor", headers=auth_headers
        )

        assert response.status_code == 200
        assert response.json()["items"]


class TestFeedback:
    async def test_records_a_judgement(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)

        response = await client.post(
            f"{API}/recommendations/{job_id}/feedback",
            headers=auth_headers,
            json={"rating": "NOT_RELEVANT"},
        )

        assert response.status_code == 204, response.text
        row = (await db_session.scalars(select(RecommendationFeedbackRow))).one()
        assert str(row.job_id) == job_id
        assert row.rating is RecommendationFeedback.NOT_RELEVANT
        # Which ranker they were reacting to. Without it the label cannot be
        # interpreted later.
        assert row.ranking_version == "v1-hand-tuned"

    async def test_changing_your_mind_replaces_rather_than_appends(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """A record of somebody changing their mind is not a training label.

        It is also the two-taps-on-a-phone case: without the upsert the second
        tap is a unique-constraint error the user did nothing to deserve.
        """
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)

        for rating in ("NOT_INTERESTED", "RELEVANT", "RELEVANT"):
            response = await client.post(
                f"{API}/recommendations/{job_id}/feedback",
                headers=auth_headers,
                json={"rating": rating},
            )
            assert response.status_code == 204, response.text

        row = (await db_session.scalars(select(RecommendationFeedbackRow))).one()
        assert row.rating is RecommendationFeedback.RELEVANT

    async def test_an_unknown_job_is_404_and_writes_nothing(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict[str, str],
    ) -> None:
        response = await client.post(
            f"{API}/recommendations/{uuid.uuid4()}/feedback",
            headers=auth_headers,
            json={"rating": "RELEVANT"},
        )

        assert response.status_code == 404
        assert (await db_session.scalars(select(RecommendationFeedbackRow))).all() == []

    async def test_an_invented_rating_is_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)

        response = await client.post(
            f"{API}/recommendations/{job_id}/feedback",
            headers=auth_headers,
            json={"rating": "LOVED_IT"},
        )

        assert response.status_code == 422

    async def test_requires_a_session(self, client: AsyncClient, seeded_skills: int) -> None:
        response = await client.post(
            f"{API}/recommendations/{uuid.uuid4()}/feedback", json={"rating": "RELEVANT"}
        )
        assert response.status_code == 401
