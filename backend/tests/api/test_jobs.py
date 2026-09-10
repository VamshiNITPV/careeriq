"""Job ingestion, browsing and import (Epic 3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_jobs_provider
from app.integrations.embeddings import FakeEmbeddingProvider
from app.integrations.jobs.fake import FakeJobProvider
from app.models.enums import UserRole
from app.models.job import Company, Job
from app.models.user import User
from app.services.embedding.indexer import index_candidates, index_jobs
from tests.fixtures.documents import build_pdf

API = "/api/v1"

# Bodies for the match-sorted browse tests. Two backend postings and one that is
# unmistakably not, so "did the ranking work?" has an answer that does not depend
# on the scoring formula's details — which are tested in test_recommendations.py.
BACKEND_BODY = """Senior Backend Engineer

About us
Zeta Labs builds payments infrastructure for teams across India.

Responsibilities
- Design and build backend services in Python
- Own services end to end, from schema to deploy

Requirements
- 5+ years of professional backend experience
- Strong Python, FastAPI and PostgreSQL
"""

SECOND_BACKEND_BODY = """Backend Python Developer

About us
Acme Technologies builds payments infrastructure for teams in India.

Responsibilities
- Build and maintain backend services in Python
- Own PostgreSQL schemas end to end

Requirements
- 4+ years of professional backend experience
- Strong Python, FastAPI and PostgreSQL
"""

NURSE_BODY = """Registered Paediatric Nurse

About us
A childrens hospital ward in Chennai.

Responsibilities
- Provide bedside nursing care on the paediatric ward
- Administer medication and record patient observations

Requirements
- Registered nursing qualification
- Two years of ward experience
"""


async def submit_job(
    client: AsyncClient, headers: dict[str, str], title: str, body: str
) -> str:
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


async def upload_and_parse(client: AsyncClient, headers: dict[str, str], run_pipeline) -> None:
    """Upload and parse a resume.

    The *pipeline* sets `current_version_id`, not the upload — and
    `default_resume_version_id` reads that, so an unparsed upload still answers
    NO_RESUME.
    """
    response = await client.post(
        f"{API}/resumes",
        headers=headers,
        files={"file": ("resume.pdf", build_pdf(), "application/pdf")},
    )
    assert response.status_code == 202, response.text
    await run_pipeline(uuid.UUID(response.json()["version_id"]))


async def index_both_sides(session: AsyncSession, provider: FakeEmbeddingProvider) -> None:
    """Embed jobs and resumes. Without both, recall answers PENDING."""
    await index_jobs(session=session, provider=provider, batch_size=500)
    await index_candidates(session=session, provider=provider, batch_size=50)


def posting(
    *,
    title: str = "Senior Backend Engineer",
    company: str = "Acme Technologies Pvt Ltd",
    extra: str = "",
) -> str:
    """A description long enough and structured enough to parse."""
    return f"""{title}

About us
{company} builds payments infrastructure for teams across India and beyond.
We are a small engineering group that ships continuously.

Location: Bengaluru, India (Hybrid)

Responsibilities
- Design and build backend services in Python
- Own services end to end, from schema to deploy
- Review code and mentor other engineers

Requirements
- 5+ years of professional backend experience
- Strong Python and PostgreSQL
- Bachelor's degree in Computer Science or equivalent

Nice to have
- Exposure to Kubernetes
- Familiarity with Docker in production

What we offer
- Compensation: 25 - 40 LPA
- Health cover for you and your family
{extra}
"""


APPLY_URL = "https://example.com/careers/apply/1"


def submission(description: str | None = None, **extra: object) -> dict[str, object]:
    """A POST /jobs body.

    source_url is required now. Deduplication keys on the description alone, so
    one URL shared by every test changes nothing about what these assert.
    """
    return {
        "description": posting() if description is None else description,
        "source_url": APPLY_URL,
        **extra,
    }


async def make_admin(db_session: AsyncSession, email: str) -> None:
    user = await db_session.scalar(select(User).where(User.email == email))
    assert user is not None
    user.role = UserRole.ADMIN
    await db_session.commit()


class TestSubmitJob:
    async def test_parses_a_pasted_description(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """US-3.1 AC2 — every field the acceptance criterion names."""
        response = await client.post(f"{API}/jobs", headers=auth_headers, json=submission())

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["is_duplicate"] is False

        job = body["job"]
        assert job["title"] == "Senior Backend Engineer"
        assert job["company"]["name"] == "Acme Technologies Pvt Ltd"
        assert job["location"] == "Bengaluru, India"
        assert job["work_mode"] == "HYBRID"
        assert job["experience_level"] == "SENIOR"
        assert job["min_years_experience"] == "5.0"
        assert job["min_education"] == "BACHELORS"
        assert job["salary_min"] == "2500000.00"
        assert job["salary_max"] == "4000000.00"
        assert job["salary_currency"] == "INR"
        assert job["salary_period"] == "YEARLY"

    async def test_splits_required_from_preferred_skills(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # The only signal the ranking formula has for weighting a skill.
        response = await client.post(f"{API}/jobs", headers=auth_headers, json=submission())
        skills = {s["name"]: s["requirement"] for s in response.json()["job"]["skills"]}

        assert skills["Python"] == "REQUIRED"
        assert skills["PostgreSQL"] == "REQUIRED"
        assert skills["Kubernetes"] == "PREFERRED"
        # "Familiarity with Docker" is hedged, even though it sits under a
        # nice-to-have heading — both routes agree here.
        assert skills["Docker"] == "PREFERRED"

    async def test_extracts_bullets_into_arrays(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        job = (await client.post(f"{API}/jobs", headers=auth_headers, json=submission())).json()[
            "job"
        ]

        assert any("backend services" in r for r in job["responsibilities"])
        assert any("years" in r for r in job["requirements"])
        assert any("Health cover" in b for b in job["benefits"])

    async def test_supplied_title_and_company_win(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # The person pasting knows what they pasted. A heuristic that overrules
        # them is infuriating.
        response = await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json=submission(title="Staff Engineer, Payments", company="Zeta Labs"),
        )
        job = response.json()["job"]
        assert job["title"] == "Staff Engineer, Payments"
        assert job["company"]["name"] == "Zeta Labs"

    async def test_rejects_text_too_short_to_be_a_posting(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # 422 with a message for the person who pasted it, not a 500 or a row
        # that scores against every candidate on no evidence.
        response = await client.post(
            f"{API}/jobs", headers=auth_headers, json=submission("Backend Engineer")
        )
        assert response.status_code == 422
        assert "too short" in response.json()["error"]["message"].lower()

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post(f"{API}/jobs", json=submission())
        assert response.status_code == 401


class TestTheApplicationLink:
    """The link the interface offers as "Apply for this job".

    It goes straight into an href on a page shared with every other user, so
    what is accepted here is a security boundary, not a formatting preference.
    """

    async def test_a_posting_needs_one(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        response = await client.post(
            f"{API}/jobs", headers=auth_headers, json={"description": posting()}
        )

        assert response.status_code == 422
        assert response.json()["error"]["details"]["fields"][0]["field"] == "source_url"

    async def test_a_link_without_a_scheme_is_accepted(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # People paste "careers.acme.com/jobs/1", and 422-ing that is pedantry.
        response = await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json=submission(source_url="careers.acme.com/jobs/1"),
        )

        assert response.status_code == 201, response.text
        assert response.json()["job"]["source_url"] == "https://careers.acme.com/jobs/1"

    @pytest.mark.parametrize(
        "link",
        [
            "javascript:alert(1)",
            "JavaScript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
            "not a url at all",
            "   ",
        ],
    )
    async def test_a_link_that_is_not_http_is_rejected(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        link: str,
    ) -> None:
        """The regression guard for an href-injection hole.

        These are rejected as a side effect of how the scheme is added — see
        normalize_url in app/schemas/urls.py. If someone ever "simplifies" that
        prefix branch, this is what fails.
        """
        response = await client.post(
            f"{API}/jobs", headers=auth_headers, json=submission(source_url=link)
        )

        assert response.status_code == 422, response.text
        assert response.json()["error"]["details"]["fields"][0]["field"] == "source_url"


class TestAddingAMissingApplicationLink:
    """PATCH /jobs/{id}/application-link — imported rows arrive without one."""

    async def test_adds_a_link_to_a_job_that_has_none(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        user_payload: dict[str, str],
        seeded_skills: int,
    ) -> None:
        await make_admin(db_session, user_payload["email"])
        imported = await client.post(
            f"{API}/admin/jobs/import",
            headers=auth_headers,
            json={
                "records": [
                    {"external_id": "L1", "description": posting(title="Imported Engineer")}
                ]
            },
        )
        assert imported.json()["created"] == 1, imported.text
        job_id = (await client.get(f"{API}/jobs", headers=auth_headers)).json()["items"][0]["id"]

        response = await client.patch(
            f"{API}/jobs/{job_id}/application-link",
            headers=auth_headers,
            # Without a scheme, because that is what people paste.
            json={"source_url": "careers.acme.com/jobs/1"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["source_url"] == "https://careers.acme.com/jobs/1"
        # And it survives the round trip, rather than only appearing in the
        # response the write returned.
        again = await client.get(f"{API}/jobs/{job_id}", headers=auth_headers)
        assert again.json()["source_url"] == "https://careers.acme.com/jobs/1"

    async def test_a_job_that_already_has_one_is_a_conflict(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """Set-only-when-null is what stops a correct link being swapped out."""
        created = await client.post(f"{API}/jobs", headers=auth_headers, json=submission())
        job_id = created.json()["job"]["id"]

        response = await client.patch(
            f"{API}/jobs/{job_id}/application-link",
            headers=auth_headers,
            json={"source_url": "https://evil.example/apply"},
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFLICT"
        detail = await client.get(f"{API}/jobs/{job_id}", headers=auth_headers)
        assert detail.json()["source_url"] == APPLY_URL

    async def test_a_stored_value_that_is_not_a_link_can_be_repaired(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """The case that made the repair form a dead end.

        Rows predate URL validation, so `source_url` can hold something that is
        not a link. The interface shows those as "no usable application link"
        and offers to fix them — but keyed purely on NULL, every such attempt
        conflicted, forever. Non-null is not the same as usable.
        """
        created = await client.post(f"{API}/jobs", headers=auth_headers, json=submission())
        job_id = created.json()["job"]["id"]
        job = await db_session.get(Job, uuid.UUID(job_id))
        assert job is not None
        job.source_url = "see the company website"
        await db_session.commit()

        response = await client.patch(
            f"{API}/jobs/{job_id}/application-link",
            headers=auth_headers,
            json={"source_url": "https://acme.example/apply/7"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["source_url"] == "https://acme.example/apply/7"

    async def test_an_unknown_job_is_404(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.patch(
            f"{API}/jobs/{uuid.uuid4()}/application-link",
            headers=auth_headers,
            json={"source_url": "https://acme.example/apply"},
        )
        assert response.status_code == 404

    async def test_rejects_a_link_that_is_not_http(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # The same guard as submission. Two entry points, one validator.
        created = await client.post(f"{API}/jobs", headers=auth_headers, json=submission())
        response = await client.patch(
            f"{API}/jobs/{created.json()['job']['id']}/application-link",
            headers=auth_headers,
            json={"source_url": "javascript:alert(1)"},
        )
        assert response.status_code == 422

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.patch(
            f"{API}/jobs/{uuid.uuid4()}/application-link",
            json={"source_url": "https://acme.example/apply"},
        )
        assert response.status_code == 401


class TestDeduplication:
    async def test_the_same_posting_returns_the_existing_job(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """US-3.2 AC2 — links to the canonical job rather than creating a row."""
        first = await client.post(f"{API}/jobs", headers=auth_headers, json=submission())
        second = await client.post(f"{API}/jobs", headers=auth_headers, json=submission())

        assert second.json()["is_duplicate"] is True
        assert second.json()["job"]["id"] == first.json()["job"]["id"]

    async def test_a_duplicate_submission_fills_in_a_missing_link(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        user_payload: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """Otherwise the submitter's link vanishes.

        Now that submission requires a link, pasting a posting the corpus
        already holds — imported, with none — would hand back a job saying "no
        application link was given" while the user is looking at the link they
        just typed.
        """
        await make_admin(db_session, user_payload["email"])
        await client.post(
            f"{API}/admin/jobs/import",
            headers=auth_headers,
            json={"records": [{"external_id": "D1", "description": posting()}]},
        )

        response = await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json=submission(source_url="https://acme.example/apply/9"),
        )

        assert response.json()["is_duplicate"] is True
        assert response.json()["job"]["source_url"] == "https://acme.example/apply/9"

    async def test_a_duplicate_never_replaces_an_existing_link(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # The row is the posting, not the submission, so the first link wins.
        await client.post(f"{API}/jobs", headers=auth_headers, json=submission())
        second = await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json=submission(source_url="https://someone-else.example/apply"),
        )

        assert second.json()["job"]["source_url"] == APPLY_URL

        listing = await client.get(f"{API}/jobs", headers=auth_headers)
        assert listing.json()["total"] == 1

    async def test_reformatted_reposts_are_caught(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # The same posting copied from two sites differs in wrapping and quote
        # characters, not in content. Stage-one hashing has to see through that
        # or every re-post falls through to the expensive comparison.
        original = posting()
        # U+2019 is the curly apostrophe a copy-paste from a job board
        # substitutes, without changing a word of the posting.
        reformatted = original.replace("\n", "\n\n").replace("'", "\u2019").upper()

        await client.post(f"{API}/jobs", headers=auth_headers, json=submission(original))
        second = await client.post(
            f"{API}/jobs", headers=auth_headers, json=submission(reformatted)
        )
        assert second.json()["is_duplicate"] is True

    async def test_a_different_posting_creates_a_new_job(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        await client.post(f"{API}/jobs", headers=auth_headers, json=submission())
        second = await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json=submission(posting(title="Frontend Engineer", extra="- Build UIs in React")),
        )
        assert second.json()["is_duplicate"] is False

        listing = await client.get(f"{API}/jobs", headers=auth_headers)
        assert listing.json()["total"] == 2


class TestCompanyResolution:
    async def test_variants_of_a_name_resolve_to_one_company(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        # Fragmenting an employer would break the "same company" scoping that
        # near-duplicate detection depends on in Phase 6.
        await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json=submission(posting(title="Role One"), company="Acme, Inc."),
        )
        await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json=submission(posting(title="Role Two"), company="ACME Inc"),
        )

        companies = list((await db_session.scalars(select(Company))).all())
        assert len(companies) == 1

    async def test_distinct_companies_stay_distinct(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json=submission(posting(title="Role One"), company="Acme Health"),
        )
        await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json=submission(posting(title="Role Two"), company="Acme Motors"),
        )

        companies = list((await db_session.scalars(select(Company))).all())
        assert len(companies) == 2


class TestBrowse:
    async def test_lists_and_filters(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        await client.post(f"{API}/jobs", headers=auth_headers, json=submission())
        await client.post(
            f"{API}/jobs",
            headers=auth_headers,
            json=submission(
                posting(title="Frontend Engineer").replace("Hybrid", "Remote"),
                title="Frontend Engineer",
            ),
        )

        everything = await client.get(f"{API}/jobs", headers=auth_headers)
        assert everything.json()["total"] == 2

        remote = await client.get(f"{API}/jobs?work_mode=REMOTE", headers=auth_headers)
        assert remote.json()["total"] == 1
        assert remote.json()["items"][0]["title"] == "Frontend Engineer"

        searched = await client.get(f"{API}/jobs?q=Frontend", headers=auth_headers)
        assert searched.json()["total"] == 1

        # The seniority filter is no longer called by the UI, which now filters
        # on years — but it is still a documented API filter, and one nothing
        # else covers. Untested and uncalled is how a filter rots into a lie in
        # the docs.
        senior = await client.get(f"{API}/jobs?experience_level=SENIOR", headers=auth_headers)
        assert senior.json()["total"] == 1
        assert senior.json()["items"][0]["title"] == "Senior Backend Engineer"

    async def test_filters_by_years_of_experience(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """A stated range is a gate; an unstated one is not.

        Covers all three storage shapes the parser can produce: a floor with no
        ceiling, an explicit two-sided range, and nothing at all.
        """
        stated = "5+ years of professional backend experience"
        for title, years in (
            ("Open Ended Engineer", stated),  # min 5, max NULL
            ("Bounded Engineer", "3-6 years of professional backend experience"),  # 3 to 6
            ("Unstated Engineer", "Deep professional backend experience"),  # both NULL
        ):
            response = await client.post(
                f"{API}/jobs",
                headers=auth_headers,
                json=submission(posting(title=title).replace(stated, years), title=title),
            )
            assert response.status_code == 201, response.text

        async def titles(query: str) -> set[str]:
            body = (await client.get(f"{API}/jobs?{query}", headers=auth_headers)).json()
            return {item["title"] for item in body["items"]}

        # Inside 3-6, below the 5+ floor, and never ruled out by the posting
        # that named no number at all.
        assert await titles("years_experience=4") == {"Bounded Engineer", "Unstated Engineer"}
        # Clears the 5+ floor, over the 3-6 ceiling.
        assert await titles("years_experience=8") == {"Open Ended Engineer", "Unstated Engineer"}
        # Zero is a filter, not an absent one.
        assert await titles("years_experience=0") == {"Unstated Engineer"}
        # One decimal place, the scale the column stores.
        assert await titles("years_experience=5.5") == {
            "Open Ended Engineer",
            "Bounded Engineer",
            "Unstated Engineer",
        }

    async def test_filters_by_how_recently_a_job_was_posted(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """A window on the posting date — and an undated posting is never hidden by it.

        Measured on the live corpus (2026-09-07): 97 of 183 active postings
        carry no date, and 90 of those came from the provider rather than from
        hand entry. Excluding them would hide more than half the corpus,
        including fetched postings that may well be recent, to make the filter
        look stricter than the data can support.
        """
        ages = {"Fresh Engineer": 2, "Stale Engineer": 45, "Undated Engineer": None}
        for title in ages:
            response = await client.post(
                f"{API}/jobs",
                headers=auth_headers,
                json=submission(posting(title=title), title=title),
            )
            assert response.status_code == 201, response.text

        # Submitted jobs are stored undated, so the dates are set here rather
        # than through the API — there is no endpoint that backdates a posting.
        now = datetime.now(UTC)
        for title, days in ages.items():
            job = await db_session.scalar(select(Job).where(Job.title == title))
            assert job is not None
            job.posted_at = None if days is None else now - timedelta(days=days)
        await db_session.commit()

        async def titles(query: str) -> set[str]:
            body = (await client.get(f"{API}/jobs?{query}", headers=auth_headers)).json()
            return {item["title"] for item in body["items"]}

        assert await titles("posted_within_days=7") == {"Fresh Engineer", "Undated Engineer"}
        assert await titles("posted_within_days=60") == {
            "Fresh Engineer",
            "Stale Engineer",
            "Undated Engineer",
        }
        # No window means no filtering, not a default window.
        assert await titles("") == {"Fresh Engineer", "Stale Engineer", "Undated Engineer"}

    async def test_rejects_an_impossible_posted_within_value(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        assert (
            await client.get(f"{API}/jobs?posted_within_days=0", headers=auth_headers)
        ).status_code == 422
        assert (
            await client.get(f"{API}/jobs?posted_within_days=900", headers=auth_headers)
        ).status_code == 422

    async def test_rejects_an_impossible_years_value(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # A typo like 600 would otherwise return everything plus every unstated
        # job, and look like the filter is broken rather than the input.
        assert (
            await client.get(f"{API}/jobs?years_experience=-1", headers=auth_headers)
        ).status_code == 422
        assert (
            await client.get(f"{API}/jobs?years_experience=600", headers=auth_headers)
        ).status_code == 422

    async def test_list_rows_omit_the_description(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # Twenty full postings to render a list of titles is hundreds of KB.
        await client.post(f"{API}/jobs", headers=auth_headers, json=submission())
        row = (await client.get(f"{API}/jobs", headers=auth_headers)).json()["items"][0]
        assert "description_raw" not in row
        assert row["skill_count"] > 0

    async def test_paginates(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        for index in range(3):
            await client.post(
                f"{API}/jobs",
                headers=auth_headers,
                json=submission(posting(title=f"Engineer {index}")),
            )

        page = await client.get(f"{API}/jobs?limit=2&offset=0", headers=auth_headers)
        assert page.json()["total"] == 3
        assert len(page.json()["items"]) == 2

    async def test_detail_returns_the_full_posting(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        created = (
            await client.post(f"{API}/jobs", headers=auth_headers, json=submission())
        ).json()["job"]

        detail = await client.get(f"{API}/jobs/{created['id']}", headers=auth_headers)
        assert detail.status_code == 200
        assert "Responsibilities" in detail.json()["description_raw"]
        # REQUIRED first: the reason to open a posting is to see what it demands.
        assert detail.json()["skills"][0]["requirement"] == "REQUIRED"

    async def test_unknown_job_is_404(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.get(f"{API}/jobs/{uuid.uuid4()}", headers=auth_headers)
        assert response.status_code == 404

    async def test_the_corpus_is_shared(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # Unlike resumes, a job submitted by one user is visible to all: it is
        # market data everyone is ranked against.
        created = (
            await client.post(f"{API}/jobs", headers=auth_headers, json=submission())
        ).json()["job"]

        other = await client.post(
            f"{API}/auth/register",
            json={"email": "other@example.com", "password": "correct-horse-9"},
        )
        other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

        response = await client.get(f"{API}/jobs/{created['id']}", headers=other_headers)
        assert response.status_code == 200


class TestMatchSortedBrowse:
    """`GET /jobs?sort=match` — the ranking reached through the browse filters.

    Until this existed the two were disjoint: browse had every filter and no
    ranking, `/recommendations` had the ranking and no filters, so "remote Python
    jobs, best match first" could not be asked for anywhere. These tests are
    mostly about the seam between them rather than about the ranking itself,
    which `test_recommendations.py` already covers.
    """

    async def test_no_resume_is_a_stated_answer_not_an_empty_list(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """An empty list with no explanation reads as "no job suits you".

        That is a far more discouraging claim than the true one, and the reader
        cannot act on it. Same contract as `/recommendations`, deliberately.
        """
        response = await client.get(f"{API}/jobs?sort=match", headers=auth_headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["availability"] == "NO_RESUME"
        assert body["items"] == []
        assert body["total"] == 0

    async def test_pending_when_the_resume_is_not_indexed_yet(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        seeded_skills: int,
        run_pipeline,
    ) -> None:
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await upload_and_parse(client, auth_headers, run_pipeline)

        body = (await client.get(f"{API}/jobs?sort=match", headers=auth_headers)).json()

        assert body["availability"] == "PENDING"
        assert body["items"] == []

    async def test_browsing_by_date_never_reports_availability(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """The default sort cannot fail these ways, so it always says READY.

        Worth pinning: a client that learned to render the NO_RESUME state must
        not start showing "upload a resume" to someone merely browsing.
        """
        body = (await client.get(f"{API}/jobs", headers=auth_headers)).json()

        assert body["availability"] == "READY"
        assert body["ranking_version"] is None

    async def test_ranks_by_score_and_scores_every_row(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider,
        run_pipeline,
    ) -> None:
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await submit_job(client, auth_headers, "Registered Paediatric Nurse", NURSE_BODY)
        await upload_and_parse(client, auth_headers, run_pipeline)
        await index_both_sides(db_session, embedding_provider)

        body = (await client.get(f"{API}/jobs?sort=match", headers=auth_headers)).json()

        assert body["availability"] == "READY"
        assert body["ranking_version"] == "v1-hand-tuned"
        scores = [Decimal(item["match_score"]) for item in body["items"]]
        assert len(scores) == 2
        assert scores == sorted(scores, reverse=True)
        # The resume is a backend one; the nursing post must not outrank it.
        assert body["items"][0]["title"] == "Senior Backend Engineer"

    async def test_a_browse_sorted_row_carries_no_score(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """Null, not zero.

        Zero would assert that the job scores nothing for this caller, which is a
        claim nothing computed (ADR-012). Null says only that no score was asked
        for here.
        """
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)

        body = (await client.get(f"{API}/jobs", headers=auth_headers)).json()

        assert body["items"][0]["match_score"] is None

    async def test_a_filter_narrows_the_ranked_set(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider,
        run_pipeline,
    ) -> None:
        """The combination that did not exist before this change.

        Filters are pushed into stage one rather than applied to its output. The
        distinction is invisible at three jobs but not at scale: recall caps at
        200, so filtering afterwards would return the remote jobs *among the 200
        nearest*, rather than the 200 nearest remote jobs.
        """
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await submit_job(client, auth_headers, "Backend Python Developer", SECOND_BACKEND_BODY)
        await submit_job(client, auth_headers, "Registered Paediatric Nurse", NURSE_BODY)
        await upload_and_parse(client, auth_headers, run_pipeline)
        await index_both_sides(db_session, embedding_provider)

        body = (
            await client.get(f"{API}/jobs?sort=match&q=Paediatric", headers=auth_headers)
        ).json()

        assert [item["title"] for item in body["items"]] == ["Registered Paediatric Nurse"]
        assert body["total"] == 1
        # Still ranked, still scored — a filter changes the set, not the mode.
        assert body["items"][0]["match_score"] is not None

    async def test_both_sorts_agree_on_what_a_filter_means(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider,
        run_pipeline,
    ) -> None:
        """The regression guard for the duplicated-predicate risk.

        Browse filters are SQLAlchemy conditions; recall is hand-written SQL.
        They share one definition (`active_job_conditions`) precisely so the two
        modes cannot drift — and drift would be silent, showing a job in one
        ordering and not in the other. This fails if anyone restates a predicate
        instead of reusing it.
        """
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await submit_job(client, auth_headers, "Backend Python Developer", SECOND_BACKEND_BODY)
        await submit_job(client, auth_headers, "Registered Paediatric Nurse", NURSE_BODY)
        await upload_and_parse(client, auth_headers, run_pipeline)
        await index_both_sides(db_session, embedding_provider)

        for filters in ("q=Backend", "q=nurse", "posted_within_days=7", ""):
            recent = await client.get(f"{API}/jobs?{filters}", headers=auth_headers)
            matched = await client.get(f"{API}/jobs?sort=match&{filters}", headers=auth_headers)

            by_date = {item["id"] for item in recent.json()["items"]}
            by_match = {item["id"] for item in matched.json()["items"]}
            assert by_date == by_match, f"the two sorts disagree about ?{filters}"

    async def test_min_score_without_match_sort_is_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """Rejected rather than ignored.

        Ignoring it would return a date-sorted list that looks like it honoured a
        threshold, and the caller cannot tell that it did not.
        """
        response = await client.get(f"{API}/jobs?min_score=60", headers=auth_headers)

        assert response.status_code == 422, response.text

    async def test_min_score_filters_the_ranked_list(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider,
        run_pipeline,
    ) -> None:
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await submit_job(client, auth_headers, "Registered Paediatric Nurse", NURSE_BODY)
        await upload_and_parse(client, auth_headers, run_pipeline)
        await index_both_sides(db_session, embedding_provider)

        everything = (await client.get(f"{API}/jobs?sort=match", headers=auth_headers)).json()
        floor = max(Decimal(item["match_score"]) for item in everything["items"])

        body = (
            await client.get(f"{API}/jobs?sort=match&min_score={floor}", headers=auth_headers)
        ).json()

        assert [item["title"] for item in body["items"]] == ["Senior Backend Engineer"]
        assert body["total"] == 1

    async def test_paging_covers_the_ranking_exactly_once(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict[str, str],
        seeded_skills: int,
        embedding_provider,
        run_pipeline,
    ) -> None:
        """Offset paging, because the browse list's page lives in its URL.

        A cursor cannot be written as `?offset=`, and `/jobs?...&offset=20` has to
        restore the list exactly — which is the whole reason browse state moved
        into the URL in the first place.
        """
        await submit_job(client, auth_headers, "Senior Backend Engineer", BACKEND_BODY)
        await submit_job(client, auth_headers, "Backend Python Developer", SECOND_BACKEND_BODY)
        await submit_job(client, auth_headers, "Registered Paediatric Nurse", NURSE_BODY)
        await upload_and_parse(client, auth_headers, run_pipeline)
        await index_both_sides(db_session, embedding_provider)

        seen: list[str] = []
        for offset in (0, 1, 2):
            body = (
                await client.get(
                    f"{API}/jobs?sort=match&limit=1&offset={offset}", headers=auth_headers
                )
            ).json()
            assert body["total"] == 3
            seen += [item["id"] for item in body["items"]]

        assert len(seen) == len(set(seen)) == 3


class TestImport:
    @pytest.fixture
    async def admin_headers(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        registered_user: dict[str, object],
        user_payload: dict[str, str],
    ) -> dict[str, str]:
        await make_admin(db_session, user_payload["email"])
        tokens = registered_user["tokens"]  # type: ignore[index]
        return {"Authorization": f"Bearer {tokens['access_token']}"}  # type: ignore[index]

    def records(self) -> list[dict[str, str]]:
        return [
            {"external_id": "a1", "description": posting(title="Engineer A")},
            {"external_id": "a2", "description": posting(title="Engineer B")},
        ]

    async def test_imports_a_batch(
        self, client: AsyncClient, admin_headers: dict[str, str], seeded_skills: int
    ) -> None:
        response = await client.post(
            f"{API}/admin/jobs/import", headers=admin_headers, json={"records": self.records()}
        )

        assert response.status_code == 200, response.text
        assert response.json()["created"] == 2
        assert response.json()["failed"] == []

    async def test_a_record_without_a_url_still_imports(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        admin_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """The importer is lenient where submission is strict, on purpose.

        A dataset row's value to the ranking formula does not depend on a link,
        and failing a whole record over a missing one makes an operator bisect
        the file for a non-reason. These rows are exactly what the detail page's
        "add the application link" control exists for.
        """
        response = await client.post(
            f"{API}/admin/jobs/import",
            headers=admin_headers,
            json={"records": [{"external_id": "n1", "description": posting(title="No Link")}]},
        )

        assert response.status_code == 200, response.text
        assert response.json()["created"] == 1
        assert response.json()["failed"] == []

        job = await db_session.scalar(select(Job).where(Job.external_id == "n1"))
        assert job is not None
        assert job.source_url is None

    async def test_an_unusable_url_costs_the_link_not_the_record(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        admin_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        """Import is the one write path that could store a non-link.

        Two things must both hold: the value never reaches the database (it
        would render as an href), and the record still imports (US-3.3 AC2 —
        a posting's skills and salary are what the ranking consumes, and they
        do not depend on the link).
        """
        response = await client.post(
            f"{API}/admin/jobs/import",
            headers=admin_headers,
            json={
                "records": [
                    {
                        "external_id": "bad-url",
                        "description": posting(title="Imported Engineer"),
                        "url": "javascript:alert(1)",
                    }
                ]
            },
        )

        assert response.json()["created"] == 1, response.text
        job = await db_session.scalar(select(Job).where(Job.external_id == "bad-url"))
        assert job is not None
        assert job.source_url is None

    async def test_a_url_without_a_scheme_is_normalised_on_import_too(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        admin_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        await client.post(
            f"{API}/admin/jobs/import",
            headers=admin_headers,
            json={
                "records": [
                    {
                        "external_id": "bare-url",
                        "description": posting(title="Imported Engineer"),
                        "url": "careers.acme.com/jobs/2",
                    }
                ]
            },
        )

        job = await db_session.scalar(select(Job).where(Job.external_id == "bare-url"))
        assert job is not None
        assert job.source_url == "https://careers.acme.com/jobs/2"

    async def test_re_running_the_same_batch_creates_nothing(
        self, client: AsyncClient, admin_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """US-3.3 AC1 — idempotency, keyed on (source, external_id)."""
        await client.post(
            f"{API}/admin/jobs/import", headers=admin_headers, json={"records": self.records()}
        )
        again = await client.post(
            f"{API}/admin/jobs/import", headers=admin_headers, json={"records": self.records()}
        )

        assert again.json()["created"] == 0
        assert again.json()["duplicates"] == 2

        listing = await client.get(f"{API}/jobs", headers=admin_headers)
        assert listing.json()["total"] == 2

    async def test_a_bad_record_does_not_abort_the_batch(
        self, client: AsyncClient, admin_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """US-3.3 AC2 — the whole point of a per-record report.

        Aborting on the first bad row makes a 10,000-record import unusable:
        nothing lands, and the operator has to bisect the file to find out why.
        """
        records = [
            {"external_id": "good-1", "description": posting(title="Engineer A")},
            {"external_id": "bad-1", "description": "too short to be a posting"},
            {"external_id": "good-2", "description": posting(title="Engineer B")},
        ]

        response = await client.post(
            f"{API}/admin/jobs/import", headers=admin_headers, json={"records": records}
        )

        body = response.json()
        assert body["created"] == 2
        assert len(body["failed"]) == 1
        assert body["failed"][0]["external_id"] == "bad-1"
        assert body["failed"][0]["index"] == 1
        assert "too short" in body["failed"][0]["reason"].lower()
        assert body["processed"] == 3

    async def test_import_is_admin_only(
        self, client: AsyncClient, auth_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # 403, not 404: the caller already knows the endpoint exists.
        response = await client.post(
            f"{API}/admin/jobs/import", headers=auth_headers, json={"records": self.records()}
        )
        assert response.status_code == 403

    async def test_imported_jobs_record_their_source(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        admin_headers: dict[str, str],
        seeded_skills: int,
    ) -> None:
        # Provenance changes how much a row is trusted.
        await client.post(
            f"{API}/admin/jobs/import", headers=admin_headers, json={"records": self.records()}
        )
        job = await db_session.scalar(select(Job).where(Job.external_id == "a1"))
        assert job is not None
        assert job.source.value == "DATASET_IMPORT"


class TestFetchJobs:
    """POST /admin/jobs/fetch (US-3.4).

    Every case runs against the FakeJobProvider the conftest injects, so nothing
    here can reach the internet. The orchestration itself is covered at the
    service level in tests/integration/test_job_fetch.py; these pin the HTTP
    contract, the admin gate and the unconfigured case.
    """

    @pytest.fixture
    async def admin_headers(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        registered_user: dict[str, object],
        user_payload: dict[str, str],
    ) -> dict[str, str]:
        await make_admin(db_session, user_payload["email"])
        tokens = registered_user["tokens"]  # type: ignore[index]
        return {"Authorization": f"Bearer {tokens['access_token']}"}  # type: ignore[index]

    async def test_fetches_and_reports(
        self, client: AsyncClient, admin_headers: dict[str, str], seeded_skills: int
    ) -> None:
        response = await client.post(
            f"{API}/admin/jobs/fetch",
            headers=admin_headers,
            json={"query": "python developer", "country": "in"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["provider"] == "fake"
        assert body["created"] == 2
        assert body["failed"] == []
        assert body["stopped_early"] is False
        # "What did that cost me" is asked at the moment the button is pressed,
        # so it belongs in the response and not only in the log.
        assert body["quota_remaining"] == 100

    async def test_fetched_jobs_are_browsable_and_filterable_by_country(
        self, client: AsyncClient, admin_headers: dict[str, str], seeded_skills: int
    ) -> None:
        # country_code had no writer at all before US-3.4, so this filter
        # returned zero rows for every job in the corpus.
        await client.post(
            f"{API}/admin/jobs/fetch", headers=admin_headers, json={"query": "python"}
        )

        listing = await client.get(f"{API}/jobs?country_code=IN", headers=admin_headers)

        assert listing.json()["total"] == 2

    async def test_refetching_creates_nothing(
        self, client: AsyncClient, admin_headers: dict[str, str], seeded_skills: int
    ) -> None:
        """US-3.4 AC1."""
        await client.post(
            f"{API}/admin/jobs/fetch", headers=admin_headers, json={"query": "python"}
        )
        again = await client.post(
            f"{API}/admin/jobs/fetch", headers=admin_headers, json={"query": "python"}
        )

        assert again.json()["created"] == 0
        assert again.json()["duplicates"] == 2
        listing = await client.get(f"{API}/jobs", headers=admin_headers)
        assert listing.json()["total"] == 2

    async def test_max_pages_is_bounded(
        self, client: AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        # The only guard against one mistyped request emptying a monthly quota.
        response = await client.post(
            f"{API}/admin/jobs/fetch",
            headers=admin_headers,
            json={"query": "python", "max_pages": 99},
        )
        assert response.status_code == 422

    async def test_fetch_is_admin_only_and_spends_no_quota(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        job_provider: FakeJobProvider,
    ) -> None:
        # 403 before the provider is ever called. A rejected request must not
        # cost a request against the vendor.
        response = await client.post(
            f"{API}/admin/jobs/fetch", headers=auth_headers, json={"query": "python"}
        )

        assert response.status_code == 403
        assert job_provider.calls == 0

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post(f"{API}/admin/jobs/fetch", json={"query": "python"})
        assert response.status_code == 401

    async def test_without_a_configured_provider_it_is_503(
        self, client: AsyncClient, admin_headers: dict[str, str]
    ) -> None:
        """The default state of the app, and it must write nothing.

        `get_job_provider()` returns None unless JOBS_PROVIDER is set —
        deliberately, because any fallback here would put invented postings into
        a corpus that real candidates get ranked against. Not configured is a
        configuration error, so 503 rather than a 200 reporting zero.
        """
        client._transport.app.dependency_overrides[get_jobs_provider] = lambda: None  # type: ignore[attr-defined]

        response = await client.post(
            f"{API}/admin/jobs/fetch", headers=admin_headers, json={"query": "python"}
        )

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
