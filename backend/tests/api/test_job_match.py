"""`GET /jobs/{id}/match` — the explainable score, end to end.

Against real PostgreSQL, because the parts most likely to be wrong are the ones
a mock cannot exercise: the candidate-to-job cosine in SQL, the taxonomy join
behind the parent/child rule, and the education fallback that reads the parsed
records when the profile field is empty.
"""

from __future__ import annotations

import math
import uuid
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_embeddings_provider
from app.integrations.embeddings import FakeEmbeddingProvider
from app.models.embedding import CandidateEmbedding, JobEmbedding
from app.models.enums import SkillRequirement, WorkMode
from app.models.job import Job, JobSkill
from app.models.profile import Profile
from app.models.skill import CandidateSkill, Skill
from app.services.embedding.indexer import index_candidates, index_jobs
from app.services.matching.weights import (
    CANDIDATE_JOB_COSINE_CEILING,
    CANDIDATE_JOB_COSINE_FLOOR,
    WEIGHTS,
    Dimension,
)
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
    """Upload the sample resume and parse it.

    The pipeline call is not optional decoration. `current_version_id` is set by
    the pipeline, not by the upload, and that column is what
    `default_resume_version_id` reads — so an unparsed upload answers NO_RESUME,
    which is correct behaviour and useless as a fixture. `run_pipeline` is a
    *callable* fixture and has to be invoked, not merely injected.
    """
    response = await client.post(
        f"{API}/resumes",
        headers=headers,
        files={"file": ("resume.pdf", build_pdf(), "application/pdf")},
    )
    assert response.status_code == 202, response.text
    await run_pipeline(uuid.UUID(response.json()["version_id"]))


def row(body: dict, dimension: Dimension) -> dict:
    (found,) = [r for r in body["breakdown"] if r["dimension"] == dimension.value]
    return found


class TestAvailability:
    async def test_no_resume_returns_a_null_score_rather_than_twenty(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """The single most important thing this endpoint does *not* do.

        With four dimensions neutral, the formula would happily produce a 20 for
        somebody the system has never seen. That is not a low score, it is a
        fabricated judgement about a person (ADR-012), and it would be the first
        thing a brand-new account saw.
        """
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)

        response = await client.get(f"{API}/jobs/{job_id}/match", headers=auth_headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["availability"] == "NO_RESUME"
        assert body["overall_score"] is None
        assert body["breakdown"] == []

    async def test_partial_when_the_vectors_are_not_built_yet(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """The common case today, and it must still be a complete answer.

        Five dimensions ran; only the semantic one could not. Returning an error
        — or an empty breakdown — would throw away the work that did succeed.
        """
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)

        response = await client.get(f"{API}/jobs/{job_id}/match", headers=auth_headers)

        body = response.json()
        assert body["availability"] == "PARTIAL"
        assert len(body["breakdown"]) == len(WEIGHTS)
        assert row(body, Dimension.SEMANTIC)["status"] == "NEEDS_DATA"
        # And the row that could not run must not blame the reader for it.
        assert "profile" not in row(body, Dimension.SEMANTIC)["reason"].lower()

    async def test_ready_once_both_sides_are_indexed(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        run_pipeline,
    ) -> None:
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)
        await index_jobs(session=db_session, provider=embedding_provider, batch_size=10)
        await index_candidates(session=db_session, provider=embedding_provider, batch_size=10)

        response = await client.get(f"{API}/jobs/{job_id}/match", headers=auth_headers)

        body = response.json()
        assert body["availability"] == "READY"
        assert row(body, Dimension.SEMANTIC)["status"] == "SCORED"

    async def test_no_provider_is_partial_not_an_error(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)
        client._transport.app.dependency_overrides[get_embeddings_provider] = lambda: None  # type: ignore[attr-defined]

        response = await client.get(f"{API}/jobs/{job_id}/match", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["availability"] == "PARTIAL"

    async def test_unknown_job_is_404(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.get(f"{API}/jobs/{uuid.uuid4()}/match", headers=auth_headers)
        assert response.status_code == 404

    async def test_a_resume_version_that_is_not_yours_is_404_not_403(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """403 would confirm the id exists — a membership oracle over other
        people's uploads."""
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)

        response = await client.get(
            f"{API}/jobs/{job_id}/match?resume_version_id={uuid.uuid4()}",
            headers=auth_headers,
        )

        assert response.status_code == 404


class TestPayload:
    async def test_the_contributions_add_up_on_screen(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """US-4.1 AC2, asserted on the JSON a reader actually receives.

        The unit tests prove the arithmetic; this proves the serialisation does
        not lose it. Decimal over JSON is exactly where a rounding guarantee
        quietly stops holding.
        """
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)

        body = (await client.get(f"{API}/jobs/{job_id}/match", headers=auth_headers)).json()

        total = sum(Decimal(r["contribution"]) for r in body["breakdown"])
        assert total == Decimal(body["overall_score"])

    async def test_the_breakdown_is_the_six_in_documented_weight_order(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)

        body = (await client.get(f"{API}/jobs/{job_id}/match", headers=auth_headers)).json()

        assert [r["dimension"] for r in body["breakdown"]] == [d.value for d in WEIGHTS]
        assert [Decimal(r["weight"]) for r in body["breakdown"]] == list(WEIGHTS.values())

    async def test_scored_weight_reports_only_the_rows_that_measured_something(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)

        body = (await client.get(f"{API}/jobs/{job_id}/match", headers=auth_headers)).json()

        expected = sum(
            (Decimal(r["weight"]) for r in body["breakdown"] if r["status"] == "SCORED"),
            start=Decimal("0"),
        )
        assert Decimal(body["scored_weight"]) == expected

    async def test_the_skill_arrays_agree_with_the_skill_row(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        """One classification pass produces both, so they cannot disagree —
        which is the failure that makes an explanation untrustworthy."""
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)

        body = (await client.get(f"{API}/jobs/{job_id}/match", headers=auth_headers)).json()

        job_response = await client.get(f"{API}/jobs/{job_id}", headers=auth_headers)
        asked = len(job_response.json()["skills"])
        counted = sum(len(body["skills"][bucket]) for bucket in ("matched", "partial", "missing"))
        assert counted == asked

    async def test_no_cosine_reaches_the_client(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        run_pipeline,
    ) -> None:
        """Unlike `/similar`, which returns a raw similarity for debugging, this
        payload carries only the rescaled score. There is nothing here a client
        could accidentally render as a percentage and be wrong about."""
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)
        await index_jobs(session=db_session, provider=embedding_provider, batch_size=10)
        await index_candidates(session=db_session, provider=embedding_provider, batch_size=10)

        body = (await client.get(f"{API}/jobs/{job_id}/match", headers=auth_headers)).json()

        assert "similarity" not in str(body)
        assert "cosine" not in str(body)


class TestSignal:
    async def test_a_related_job_scores_above_an_unrelated_one(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        run_pipeline,
    ) -> None:
        """The assertion that says the feature works at all.

        The sample resume is a Python backend engineer's, so a paediatric
        nursing post must score below a backend one end to end.

        Asserted on the total rather than on the semantic row, and the reason is
        worth stating: `FakeEmbeddingProvider` is a hashing trick over a sparse
        token space, so *both* of its candidate-job cosines land under the
        measured floor and rescale to zero. That is a property of the fake, not
        of the formula — the real model's candidate-job cosines run 0.22 to 0.75
        (weights.py). The rescale itself is asserted on exact geometry in
        `test_the_semantic_dimension_rescales_a_known_cosine`, and across the
        whole range in the unit tests.
        """
        backend = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        nursing = await submit(client, auth_headers, "Registered Paediatric Nurse", UNRELATED)
        await upload_resume(client, auth_headers, run_pipeline)
        await index_jobs(session=db_session, provider=embedding_provider, batch_size=10)
        await index_candidates(session=db_session, provider=embedding_provider, batch_size=10)

        good = (await client.get(f"{API}/jobs/{backend}/match", headers=auth_headers)).json()
        bad = (await client.get(f"{API}/jobs/{nursing}/match", headers=auth_headers)).json()

        assert Decimal(good["overall_score"]) > Decimal(bad["overall_score"])

    async def test_a_parent_skill_earns_a_partial_credit_through_the_taxonomy(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        registered_user: dict[str, object],
        run_pipeline,
    ) -> None:
        """The React-implies-JavaScript rule, against the real taxonomy table.

        Worth an integration test rather than only a unit one: the rule depends
        on `Skill.parent_skill_id` actually being populated by the seed, and a
        unit test with a hand-built mapping would pass over an empty taxonomy.
        """
        user_id = uuid.UUID(str(registered_user["user"]["id"]))  # type: ignore[index]
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)

        # A child skill on the job that the candidate does not hold, whose
        # parent they do.
        parent = Skill(name="Widgetry", normalized_name="widgetry", aliases=[])
        db_session.add(parent)
        await db_session.flush()
        child = Skill(
            name="Widgetry Pro",
            normalized_name="widgetry pro",
            aliases=[],
            parent_skill_id=parent.id,
        )
        db_session.add(child)
        await db_session.flush()

        job = await db_session.get(Job, job_id)
        assert job is not None
        # Replace the job's requirements so the assertion is about this one pair
        # rather than about whatever the parser happened to extract.
        #
        # Through the relationship, not with a DELETE plus an INSERT beside it.
        # `Job.skills` is already loaded in this identity map, and the endpoint
        # reads that same collection — writing around it leaves the test
        # asserting against a stale in-memory list. `delete-orphan` issues the
        # DELETEs.
        job.skills.clear()
        job.skills.append(
            JobSkill(skill_id=child.id, requirement=SkillRequirement.REQUIRED)
        )
        db_session.add(CandidateSkill(user_id=user_id, skill_id=parent.id))
        await db_session.flush()

        body = (await client.get(f"{API}/jobs/{job_id}/match", headers=auth_headers)).json()

        assert [s["name"] for s in body["skills"]["partial"]] == ["Widgetry Pro"]
        assert Decimal(row(body, Dimension.SKILL)["score"]) == Decimal("0.5000")

    async def test_setting_preferred_locations_turns_the_location_row_from_grey_to_scored(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        registered_user: dict[str, object],
        run_pipeline,
    ) -> None:
        """The test that the honest-degradation design actually pays off.

        A user who fills in something they were asked for must see the formula
        start using it, and `scored_weight` rise. If it does not, the call to
        action on the row is a dead end and the whole disclosure is theatre.
        """
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)

        job = await db_session.get(Job, job_id)
        assert job is not None
        job.location = "Bengaluru, Karnataka, IN"
        job.country_code = "IN"
        job.work_mode = WorkMode.ONSITE
        await db_session.flush()

        # Cleared deliberately. The parser reads a location off the resume
        # header, so a freshly parsed profile is *not* the empty state this test
        # is about — without this the row starts SCORED and the test asserts
        # nothing. (That the parser fills it is good; it is simply not the case
        # under test.)
        profile = await db_session.scalar(
            select(Profile).where(Profile.user_id == uuid.UUID(str(registered_user["user"]["id"])))  # type: ignore[index]
        )
        assert profile is not None
        profile.location = None
        profile.country_code = None
        profile.preferred_locations = []
        await db_session.flush()

        before = (await client.get(f"{API}/jobs/{job_id}/match", headers=auth_headers)).json()
        assert row(before, Dimension.LOCATION)["status"] == "NEEDS_PROFILE"

        profile = await db_session.scalar(
            select(Profile).where(Profile.user_id == uuid.UUID(str(registered_user["user"]["id"])))  # type: ignore[index]
        )
        assert profile is not None
        profile.preferred_locations = ["Bengaluru"]
        await db_session.flush()

        after = (await client.get(f"{API}/jobs/{job_id}/match", headers=auth_headers)).json()

        assert row(after, Dimension.LOCATION)["status"] == "SCORED"
        assert Decimal(row(after, Dimension.LOCATION)["score"]) == Decimal("1.0000")
        assert Decimal(after["scored_weight"]) > Decimal(before["scored_weight"])
        assert Decimal(after["overall_score"]) > Decimal(before["overall_score"])

    async def test_a_needs_data_row_never_offers_the_user_a_remedy(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        registered_user: dict[str, object],
        run_pipeline,
    ) -> None:
        """A posting that does not say where it is must not produce a sentence
        telling the reader to fix their profile. R3, at the boundary where it
        matters most."""
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)

        job = await db_session.get(Job, job_id)
        assert job is not None
        job.location = None
        job.country_code = None
        job.work_mode = WorkMode.ONSITE
        await db_session.flush()

        profile = await db_session.scalar(
            select(Profile).where(Profile.user_id == uuid.UUID(str(registered_user["user"]["id"])))  # type: ignore[index]
        )
        assert profile is not None
        profile.preferred_locations = ["Bengaluru"]
        await db_session.flush()

        body = (await client.get(f"{API}/jobs/{job_id}/match", headers=auth_headers)).json()

        location_row = row(body, Dimension.LOCATION)
        assert location_row["status"] == "NEEDS_DATA"
        assert "your profile" not in location_row["reason"].lower()

    async def test_the_semantic_dimension_rescales_a_known_cosine(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider: FakeEmbeddingProvider,
        run_pipeline,
    ) -> None:
        """The rescale, on geometry chosen rather than hashed.

        The stored vectors are overwritten with a constructed orthonormal pair
        whose cosine is exactly the midpoint of the measured candidate-job range,
        which must rescale to 0.5. Overwriting rather than steering the provider
        is deliberate: it removes the document text from the test entirely, so
        what is asserted is the SQL cosine and the rescale, not the tokeniser.
        """
        job_id = await submit(client, auth_headers, "Senior Backend Engineer", BACKEND)
        await upload_resume(client, auth_headers, run_pipeline)
        await index_jobs(session=db_session, provider=embedding_provider, batch_size=10)
        await index_candidates(session=db_session, provider=embedding_provider, batch_size=10)

        target = (CANDIDATE_JOB_COSINE_FLOOR + CANDIDATE_JOB_COSINE_CEILING) / 2
        cosine = float(target)
        dimensions = embedding_provider.dimensions
        # Two unit vectors at exactly `cosine`: one on the first axis, the other
        # rotated into the second by acos(cosine).
        a = [1.0] + [0.0] * (dimensions - 1)
        b = [cosine, math.sqrt(1 - cosine * cosine)] + [0.0] * (dimensions - 2)

        job_vector = (await db_session.scalars(select(JobEmbedding))).one()
        candidate_vector = (await db_session.scalars(select(CandidateEmbedding))).one()
        job_vector.embedding = a
        candidate_vector.embedding = b
        await db_session.flush()

        body = (await client.get(f"{API}/jobs/{job_id}/match", headers=auth_headers)).json()

        assert body["availability"] == "READY"
        assert Decimal(row(body, Dimension.SEMANTIC)["score"]) == Decimal("0.5000")
